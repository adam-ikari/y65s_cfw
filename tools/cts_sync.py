#!/usr/bin/env -S uv run python
"""cts_sync.py -- read/write the module's clock over BLE (Current Time Service).

The screen module is a BLE peripheral that exposes the standard Current Time
Service (0x1805): the *central* (a phone, or us) writes the Current Time
characteristic (0x2A2B) and the module applies it.  That is the only channel
that has ever been observed to move the module's clock -- the USB vendor
channel has no such command.

Windows ships no CTS provider, so we act as the central ourselves: pair the
keyboard with the PC over Bluetooth (Fn+Z = BT1), then run this.

    uv run tools/cts_sync.py --list          # show nearby devices and services
    uv run tools/cts_sync.py --read           # read the module's clock
    uv run tools/cts_sync.py --write          # push the PC's clock into it
    uv run tools/cts_sync.py --write --offset -7   # push a corrected clock

Needs the `bleak` package (uv resolves it) and a keyboard already paired.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import struct
import sys
import time

CT_SERVICE = "00001805-0000-1000-8000-00805f9b34fb"
CT_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
CT_TIME_ZONE = "00002a0e-0000-1000-8000-00805f9b34fb"
CT_DAYLIGHT = "00002a0d-0000-1000-8000-00805f9b34fb"

# Current Time: epoch seconds (uint32), fractional seconds (uint8), DST (uint8)
TIME_LEN = 6


async def scan(timeout: float) -> list:
    from bleak import BleakScanner

    print(f"scanning for BLE devices ({timeout:.0f}s) ...")
    return await BleakScanner.discover(timeout=timeout, return_adv=True)


async def show_devices(timeout: float) -> int:
    found = await scan(timeout)
    items = found.items() if isinstance(found, dict) else [(getattr(d, "address", "?"), (d, adv))
                                                           for d, adv in found]
    rows = []
    for addr, pair in items:
        d, adv = (pair if isinstance(pair, tuple) and len(pair) == 2 else (pair, None))
        name = (getattr(d, "name", None) or getattr(adv, "local_name", None) or "?")
        uuids = [u.lower() for u in (getattr(adv, "service_uuids", None) or [])]
        rssi = getattr(adv, "rssi", "?")
        rows.append((str(name).lower(), name, addr, rssi, uuids,
                     CT_SERVICE in uuids))
    for _, name, addr, rssi, uuids, cts in sorted(rows):
        print(f"  {name:28s} {addr}  rssi={rssi}  {'CTS' if cts else ''} "
              f"{' '.join(uuids)}")
    return 0


def _find_cts(client) -> bool:
    for service in client.services:
        if service.uuid.lower() == CT_SERVICE:
            for char in service.characteristics:
                if char.uuid.lower() == CT_CURRENT_TIME:
                    return True
    return False


async def with_device(address: str, mode: str, offset: int) -> int:
    from bleak import BleakClient

    async with BleakClient(address) as client:
        if not _find_cts(client):
            print("该设备没有暴露 Current Time Service (0x1805)")
            print("可用的服务: " + ", ".join(s.uuid for s in client.services))
            return 2

        char = None
        for service in client.services:
            for c in service.characteristics:
                if c.uuid.lower() == CT_CURRENT_TIME:
                    char = c
        if char is None:
            print("没有 Current Time 特性 0x2A2B")
            return 2

        raw = await client.read_gatt_char(char)
        epoch, frac, dst = struct.unpack("<IBB", bytes(raw[:TIME_LEN]))
        print(f"模块当前时间: {dt.datetime.fromtimestamp(epoch)}  frac={frac} dst={dst}")

        if mode == "read":
            return 0

        now = dt.datetime.now() + dt.timedelta(minutes=offset)
        epoch = int(now.timestamp())
        payload = struct.pack("<IBB", epoch, 0, 0)
        try:
            await client.write_gatt_char(char, payload, response=True)
        except Exception as exc:                      # some CTS chars are
            print(f"带响应写失败({exc})，改用无响应写")   # write-without-response
            await client.write_gatt_char(char, payload, response=False)
        print(f"已写入: {now:%Y-%m-%d %H:%M:%S} (epoch={epoch}, offset={offset} min)")
        time.sleep(0.4)
        raw = await client.read_gatt_char(char)
        epoch2 = struct.unpack("<I", bytes(raw[:4]))[0]
        print(f"回读: {dt.datetime.fromtimestamp(epoch2)}  "
              f"偏差 {int(epoch2 - epoch)} s")
        return 0


async def dump_services(address: str) -> int:
    from bleak import BleakClient

    print(f"connecting to {address} ...", flush=True)
    try:
        async with BleakClient(address, timeout=15) as client:
            print(f"connected: {client.address}  name={getattr(client, 'name', '?')}",
                  flush=True)
            for service in client.services:
                print(f"service {service.uuid}  ({service.description})")
                for char in service.characteristics:
                    props = ",".join(char.properties)
                    print(f"   char {char.uuid}  props=[{props}]  "
                          f"desc={char.description}")
                    for desc in char.descriptors:
                        print(f"      desc {desc.uuid}  {desc.description}")
    except Exception as exc:
        print(f"连接/服务发现失败: {type(exc).__name__}: {exc}")
        print("提示：Windows 的 BLE HID 驱动可能已独占该设备的 GATT 连接，"
              "第三方 GATT 客户端连不上属正常。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="scan and list devices")
    ap.add_argument("--dump", action="store_true",
                    help="connect and print every GATT service/characteristic")
    ap.add_argument("--read", action="store_true", help="read the module clock")
    ap.add_argument("--write", action="store_true", help="write the PC clock")
    ap.add_argument("--address", help="BLE address of the keyboard")
    ap.add_argument("--offset", type=int, default=0,
                    help="minutes to add to the PC clock (use -7 if the source "
                         "device is ahead)")
    ap.add_argument("--timeout", type=float, default=8.0)
    a = ap.parse_args()

    async def run() -> int:
        if a.dump and a.address:
            return await dump_services(a.address)
        if a.list or not a.address:
            return await show_devices(a.timeout)
        mode = "write" if a.write else "read"
        return await with_device(a.address, mode, a.offset)

    try:
        return asyncio.run(run())
    except ImportError:
        print("需要 bleak：uv run --with bleak tools/cts_sync.py ...")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
