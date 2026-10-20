#!/usr/bin/env -S uv run python
"""cts_sync.py -- read and write the module's clock over BLE.

The screen module is a BLE peripheral (name "YD-Y65S-5.0", address
FF:26:00:0F:0A:56, BLE VID/PID 0204:B35A).  Its GATT map is:

    0x1800  0x2A00 device name, 0x2A01 appearance, 0x2A04 conn params
    0x1812  HID                       (Windows blocks 3rd-party access to it)
    0x180F  0x2A19 battery level     (read only)
    0x180A  0x2A29/24/25/27/26/28/50 device information
    0xF200  0xF202  <-- the module's clock / control channel (9 bytes)

0xF202 is the only writable vendor characteristic and it is what a phone
writes the time into; the module keeps that value in its own RTC (which is
persistent, and runs at the right rate -- it is just never corrected).

Windows has no Current Time Service provider, so we act as the BLE central
ourselves.  bleak cannot be used: the device is paired and connected (it
stops advertising), and bleak can only reach devices it has seen
advertising.  So we talk to WinRT directly (BluetoothLEDevice), which works
fine on an already-connected device.

    uv run tools/cts_sync.py --read
    uv run tools/cts_sync.py --write
    uv run tools/cts_sync.py --write --offset -6      # if the source is ahead
    uv run tools/cts_sync.py --sweep                  # try every time layout
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import struct
import sys

ADDRESS = 0xFF26000F0A56
F202 = "0000f202-0000-1000-8000-00805f9b34fb"
BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"


def _bytes_of(value) -> bytes:
    for attr in ("buffer", "data", "value", "raw"):
        if hasattr(value, attr):
            try:
                return bytes(getattr(value, attr))
            except Exception:
                pass
    try:
        return bytes(value)
    except Exception:
        return repr(value).encode()


def _bcd(n: int) -> int:
    return ((n // 10) << 4) | (n % 10)


def pack_time(now: dt.datetime, fmt: str) -> bytes:
    """Build the 9 bytes for characteristic 0xF202.

    odm-bcd   5A 01 5A | BCD yy mm dd hh mi ss
    odm-dec   5A 01 5A | dec  yy mm dd hh mi ss
    bcd       BCD yy mm dd hh mi ss wd | 00 00
    epoch     uint32 LE unix epoch | 00 00 00 00 00
    """
    y, mo, d = now.year % 100, now.month, now.day
    h, mi, s = now.hour, now.minute, now.second
    wd = (now.weekday() + 1) % 7
    if fmt == "odm-bcd":
        return bytes([0x5A, 0x01, 0x5A] + [_bcd(x) for x in (y, mo, d, h, mi, s)])
    if fmt == "odm-dec":
        return bytes([0x5A, 0x01, 0x5A] + [x & 0xFF for x in (y, mo, d, h, mi, s)])
    if fmt == "bcd":
        return bytes([_bcd(x) for x in (y, mo, d, h, mi, s, wd)] + [0, 0])
    if fmt == "epoch":
        return struct.pack("<I", int(now.timestamp())) + bytes(5)
    raise ValueError(f"unknown format {fmt}")


async def _open():
    from winrt.windows.devices.bluetooth import BluetoothLEDevice

    return await BluetoothLEDevice.from_bluetooth_address_async(ADDRESS)


async def _find(dev, uuid: str):
    res = await dev.get_gatt_services_async()
    for s in res.services:
        try:
            chars = s.get_all_characteristics()
        except Exception:
            continue
        for c in chars:
            if str(c.uuid).lower() == uuid:
                return c
    return None


async def read_all() -> int:
    dev = await _open()
    res = await dev.get_gatt_services_async()
    for s in res.services:
        try:
            chars = s.get_all_characteristics()
        except Exception:
            print(f"{s.uuid}  <blocked by policy>")
            continue
        for c in chars:
            try:
                data = _bytes_of(await c.read_value_async())
                show = data.hex(" ") if len(data) <= 48 else data[:48].hex(" ") + "..."
            except Exception as exc:
                show = f"<read err {str(exc)[:40]}>"
            print(f"{s.uuid}  {c.uuid}  = {show}")
    return 0


async def read_clock() -> int:
    dev = await _open()
    char = await _find(dev, F202)
    if char is None:
        print("找不到厂商特征 0xF202")
        return 2
    data = _bytes_of(await char.read_value_async())
    print(f"0xF202 = {data.hex(' ')}")
    for fmt in ("odm-bcd", "odm-dec", "bcd", "epoch"):
        try:
            packed = pack_time(dt.datetime(2000, 1, 1), fmt)
        except Exception:
            continue
    print("  (解码需要知道格式；见 --sweep)")
    return 0


async def write_time(offset: int, fmt: str, when: dt.datetime | None = None) -> int:
    dev = await _open()
    char = await _find(dev, F202)
    if char is None:
        print("找不到厂商特征 0xF202")
        return 2
    now = when or (dt.datetime.now() + dt.timedelta(minutes=offset))
    payload = pack_time(now, fmt)
    payload = (payload + bytes(9))[:9]
    try:
        await char.write_value_with_result_async(payload)
    except Exception as exc:
        print(f"带响应写失败({exc})，改用无响应写")
        await char.write_value_async(payload)
    print(f"已写入 {fmt}: {now:%Y-%m-%d %H:%M:%S}  bytes={payload.hex(' ')}")
    await asyncio.sleep(0.4)
    try:
        back = _bytes_of(await char.read_value_async())
        print(f"回读 0xF202 = {back.hex(' ')}")
    except Exception as exc:
        print(f"回读失败: {exc}")
    return 0


async def sweep() -> int:
    """Write one candidate per format, each with a distinct time.

    The screen shows the time, so whatever the module accepted last is
    visible; the minute tells which layout was right.
    """
    base = dt.datetime.now().replace(second=0, microsecond=0)
    fmts = ["odm-bcd", "odm-dec", "bcd", "epoch"]
    for i, fmt in enumerate(fmts):
        when = base + dt.timedelta(minutes=i)
        print(f"--- {fmt} -> {when:%H:%M}")
        await write_time(0, fmt, when)
        await asyncio.sleep(0.5)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--read", action="store_true", help="read the module clock")
    ap.add_argument("--all", action="store_true", help="dump every characteristic")
    ap.add_argument("--write", action="store_true", help="write the PC clock")
    ap.add_argument("--offset", type=int, default=0,
                    help="minutes added to the PC clock")
    ap.add_argument("--fmt", default="odm-bcd",
                    help="odm-bcd | odm-dec | bcd | epoch")
    ap.add_argument("--sweep", action="store_true",
                    help="try every layout, one per minute")
    a = ap.parse_args()

    async def run() -> int:
        if a.all:
            return await read_all()
        if a.sweep:
            return await sweep()
        if a.read:
            return await read_clock()
        if a.write:
            return await write_time(a.offset, a.fmt)
        return await read_clock()

    try:
        return asyncio.run(run())
    except ImportError:
        print("需要 winrt：uv run --with bleak tools/cts_sync.py ...")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
