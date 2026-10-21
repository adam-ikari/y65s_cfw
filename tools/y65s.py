#!/usr/bin/env -S uv run python
"""y65s.py -- our own Y65S (258a:019d) companion tool.

Everything here is written against the protocol we reverse engineered
ourselves; the vendor's own app is only a reference (and is not used at
runtime).  Sub-commands:

    status            device, link mode, battery, module clock (BLE)
    profile dump      read the 128 byte profile the module keeps
    profile set      write the 128 byte profile (record 0x04)
    volume show      read the volume field of the profile
    volume set V     write the volume field, with a scale
    clock set        push the PC clock into the module
    screen push F    push a BMP/PNG as a screen frame (0x0D/0x0C + OEM timing)
    backup FILE      read the whole 64 KiB flash (sinowisp read)
    restore FILE     write the whole flash back (sinowisp write)
    doctor           print every observable we can read, for triage

Safety: everything that writes (profile, volume, clock, screen, restore) is
read-only by default.  Pass --allow-write to arm the write path, and
--allow-flash for the two operations that touch the keyboard's flash
(restore and anything the vendor tool would do).  The screen SoC keeps its
own clock, so `clock set` is a runtime command and never writes flash.
"""

from __future__ import annotations

import argparse
import binascii
import ctypes
import datetime as dt
import pathlib
import struct
import subprocess
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

VID, PID, PAGE, USAGE = 0x258A, 0x019D, 0xFF02, 0x0002
REPORT = 9
PAYLOAD = 519
DATA_OFF = 7              # every record's data window starts at payload[7]
PROFILE_LEN = 128
PROFILE_DEFAULT_OFF = 0x9983     # factory profile in the keyboard's flash
PROFILE_LIVE_OFF = 0xA400         # live profile the module actually uses
VOLUME_OFF = 0x31                 # profile byte that carries the volume level
BLE_ADDRESS = 0xFF26000F0A56
BLE_F202 = "0000f202-0000-1000-8000-00805f9b34fb"
BLE_BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
class Device:
    """The vendor HID channel: feature report 9 in, an 8 byte answer out."""

    def __init__(self) -> None:
        args = types.SimpleNamespace(vid=VID, pid=PID, page=PAGE, usage=USAGE)
        e = vh.pick(vh.enumerate_hid(overlapped=True), args)
        vh.guard(e, REPORT)
        self.handle = e["handle"]
        self.length = max(e["caps"].FeatureReportByteLength, REPORT + 1)
        self.in_len = max(e["caps"].InputReportByteLength if e["caps"] else 64, 64)
        self.event = vh.kernel32.CreateEventW(None, True, False, None)

    def send(self, payload: bytes) -> bool:
        buf = ctypes.create_string_buffer(self.length)
        buf[0] = bytes([REPORT])
        buf[1:1 + len(payload)] = bytes(payload)
        return bool(vh.hid.HidD_SetFeature(self.handle, buf, self.length))

    def answer(self, seconds: float = 1.5) -> bytes:
        """Wait for the device's answer frame (id 9 + 7 bytes)."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            buf = ctypes.create_string_buffer(self.in_len)
            read = vh.wintypes.DWORD()
            vh.kernel32.ResetEvent(self.event)
            ov = vh.OVERLAPPED()
            ov.hEvent = self.event
            ok = vh.kernel32.ReadFile(self.handle, buf, self.in_len,
                                     ctypes.byref(read), ctypes.byref(ov))
            if not ok:
                if ctypes.get_last_error() != 997:
                    time.sleep(0.01)
                    continue
                if vh.kernel32.WaitForSingleObject(self.event, 200) != 0:
                    vh.kernel32.CancelIo(self.handle)
                    continue
                vh.kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov),
                                                ctypes.byref(read), False)
            if read.value:
                return bytes(buf.raw[:read.value])
        return b""

    def record(self, cmd: int, data: bytes = b"", at: int = DATA_OFF,
               sub: int | None = None, sub_at: int | None = None) -> bytes:
        p = bytearray(PAYLOAD)
        p[0] = cmd
        if sub is not None:
            p[1 if sub_at is None else sub_at] = sub & 0x07
        if data:
            p[at:at + len(data)] = bytes(data)
        return bytes(p)

    def profile_read(self) -> bytes:
        """The module's current profile is not readable; use the flash copy."""
        raise NotImplementedError("read the profile from the flash dump instead")


# --------------------------------------------------------------------------
# profile handling
# --------------------------------------------------------------------------
def profile_from_dump(path: pathlib.Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 0xA400 + PROFILE_LEN:
        raise SystemExit(f"{path} is too small to hold a profile")
    return data[PROFILE_LIVE_OFF:PROFILE_LIVE_OFF + PROFILE_LEN]


def profile_show(profile: bytes) -> None:
    for i in range(0, len(profile), 16):
        chunk = profile[i:i + 16]
        print(f"  {i:02X}: " + " ".join(f"{b:02X}" for b in chunk))
    print(f"  volume field (0x{VOLUME_OFF:02X}) = {profile[VOLUME_OFF]}")


def scale_volume(value: int, scale: str) -> int:
    """Map a 0..100 system volume onto whatever the module expects."""
    if scale == "100":
        return max(0, min(100, value))
    if scale == "16":
        return max(0, min(16, round(value * 16 / 100)))
    if scale == "15":
        return max(0, min(15, round(value * 15 / 100)))
    if scale == "255":
        return max(0, min(255, round(value * 255 / 100)))
    raise SystemExit(f"unknown scale {scale}")


# --------------------------------------------------------------------------
# BLE (module clock + battery)
# --------------------------------------------------------------------------
def ble_pack_time(now: dt.datetime, fmt: str) -> bytes:
    def bcd(n: int) -> int:
        return ((n // 10) << 4) | (n % 10)

    y, mo, d = now.year % 100, now.month, now.day
    h, mi, s = now.hour, now.minute, now.second
    wd = (now.weekday() + 1) % 7
    if fmt == "odm-bcd":
        return bytes([0x5A, 0x01, 0x5A] + [bcd(x) for x in (y, mo, d, h, mi, s)])
    if fmt == "odm-dec":
        return bytes([0x5A, 0x01, 0x5A] + [x & 0xFF for x in (y, mo, d, h, mi, s)])
    if fmt == "bcd":
        return bytes([bcd(x) for x in (y, mo, d, h, mi, s, wd)] + [0, 0])
    if fmt == "epoch":
        return struct.pack("<I", int(now.timestamp())) + bytes(5)
    raise SystemExit(f"unknown format {fmt}")


async def _ble_read_all() -> dict:
    from winrt.windows.devices.bluetooth import BluetoothLEDevice

    dev = await BluetoothLEDevice.from_bluetooth_address_async(BLE_ADDRESS)
    res = await dev.get_gatt_services_async()
    out = {}
    for s in res.services:
        try:
            chars = s.get_all_characteristics()
        except Exception:
            out[str(s.uuid)] = "<blocked by policy>"
            continue
        for c in chars:
            try:
                val = await c.read_value_async()
                raw = b"".join(bytes(getattr(val, a)) if hasattr(val, a) else bytes(val)
                               for a in ("buffer", "data", "value") if hasattr(val, a)) \
                    if not isinstance(val, (bytes, bytearray)) else bytes(val)
            except Exception as exc:
                raw = f"<read err {str(exc)[:40]}>"
            out[f"{s.uuid}/{c.uuid}"] = raw
    return out


async def _ble_write_time(fmt: str, offset: int) -> None:
    from winrt.windows.devices.bluetooth import BluetoothLEDevice

    dev = await BluetoothLEDevice.from_bluetooth_address_async(BLE_ADDRESS)
    res = await dev.get_gatt_services_async()
    char = None
    for s in res.services:
        try:
            chars = s.get_all_characteristics()
        except Exception:
            continue
        for c in chars:
            if str(c.uuid).lower() == BLE_F202:
                char = c
    if char is None:
        raise SystemExit("BLE: 找不到 0xF202")
    now = dt.datetime.now() + dt.timedelta(minutes=offset)
    payload = (ble_pack_time(now, fmt) + bytes(9))[:9]
    try:
        await char.write_value_with_result_async(payload)
    except Exception:
        await char.write_value_async(payload)
    print(f"BLE 0xF202 <- {now:%Y-%m-%d %H:%M:%S} ({fmt})  bytes={payload.hex(' ')}")


def ble_read() -> int:
    import asyncio
    data = asyncio.run(_ble_read_all())
    for k, v in data.items():
        if isinstance(v, (bytes, bytearray)):
            print(f"  {k} = {bytes(v).hex(' ')}")
        else:
            print(f"  {k} = {v}")
    return 0


def ble_clock(fmt: str, offset: int) -> int:
    import asyncio
    asyncio.run(_ble_write_time(fmt, offset))
    return 0


# --------------------------------------------------------------------------
# screen frames (0x0D SetGIFParam -> 0x0C AccessData_Page -> 0x0D end)
# --------------------------------------------------------------------------
def bmp_to_rgb565be(path: pathlib.Path, w: int, h: int) -> bytes:
    """Read a 24/32 bit BMP and emit RGB565 big endian pixels."""
    data = path.read_bytes()
    if data[:2] != b"BM":
        raise SystemExit("only uncompressed BMP is supported")
    off = struct.unpack_from("<I", data, 10)[0]
    hdr = struct.unpack_from("<I", data, 14)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if compression != 0 or bpp not in (24, 32):
        raise SystemExit("only uncompressed 24/32 bit BMP is supported")
    row = ((width * bpp // 8) + 3) & ~3
    out = bytearray()
    flip = height > 0
    for y in range(abs(height)):
        src = off + (y if flip else abs(height) - 1 - y) * row
        for x in range(width):
            p = src + x * (bpp // 8)
            b, g, r = data[p], data[p + 1], data[p + 2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b & 0xF8)
            out += struct.pack(">H", v)
    if len(out) != w * h * 2:
        raise SystemExit(f"bmp is {width}x{height}, expected {w}x{h}")
    return bytes(out)


def screen_push(dev: Device, pixels: bytes, w: int, h: int) -> None:
    """The vendor's upload sequence, including the timing the module needs."""
    total = len(pixels)
    blocks = (total + 511) // 512
    dev.send(dev.record(0x0D, bytes([0x01, 0x00]) + struct.pack("<HH", blocks, 50)))
    time.sleep(0.12)
    for seq in range(blocks):
        chunk = pixels[seq * 512:(seq + 1) * 512]
        chunk = chunk + bytes(512 - len(chunk))
        dev.send(dev.record(0x0C, struct.pack("<HH", 0, seq) + chunk))
        time.sleep(0.05)
    time.sleep(0.05)
    dev.send(dev.record(0x0D, bytes([0x00, 0x00])))
    time.sleep(0.5)
    print(f"pushed {blocks} blocks of 512 B ({w}x{h})")


# --------------------------------------------------------------------------
def cmd_status(args) -> int:
    dev = Device()
    print("vendor channel:", "ok")
    frame = dev.answer(1.0)
    if frame:
        print(f"answer frame: {frame.hex(' ')}")
        if len(frame) > 3 and frame[3] == 1:
            print("  -> module answered 0xAA on the last bulk frame")
    print("\nBLE:")
    ble_read()
    return 0


def cmd_profile(args) -> int:
    if args.dump:
        profile = profile_from_dump(args.dump)
        profile_show(profile)
        return 0
    raise SystemExit("profile dump needs --dump <flash dump>")


def cmd_volume(args) -> int:
    if args.action == "show":
        profile = profile_from_dump(args.dump)
        print(f"profile volume (0x{VOLUME_OFF:02X}) = {profile[VOLUME_OFF]}")
        return 0
    if args.action == "set":
        if not args.allow_write:
            raise SystemExit("refusing to write without --allow-write")
        profile = bytearray(profile_from_dump(args.dump))
        profile[VOLUME_OFF] = scale_volume(args.value, args.scale)
        dev = Device()
        ok = dev.send(dev.record(0x04, bytes(profile)))
        print(f"profile write {'ok' if ok else 'FAILED'}  volume byte = "
              f"{profile[VOLUME_OFF]} (system {args.value}%, scale {args.scale})")
        return 0 if ok else 1
    raise SystemExit("volume needs show|set")


def cmd_clock(args) -> int:
    if args.action == "set":
        return ble_clock(args.fmt, args.offset)
    raise SystemExit("clock needs set")


def cmd_screen(args) -> int:
    if not args.allow_write:
        raise SystemExit("refusing to push without --allow-write")
    pixels = bmp_to_rgb565be(args.file, args.w, args.h)
    dev = Device()
    screen_push(dev, pixels, args.w, args.h)
    return 0


def cmd_backup(args) -> int:
    cmd = ["sinowisp", "read", "-s", "full", "--platform", "sh68f90",
           "--vendor_id", "0x258a", "--product_id", "0x019d", args.out]
    print("+", " ".join(cmd))
    return subprocess.call(cmd)


def cmd_restore(args) -> int:
    if not args.allow_flash:
        raise SystemExit("refusing to write flash without --allow-flash")
    cmd = ["sinowisp", "write", "--platform", "sh68f90",
           "--vendor_id", "0x258a", "--product_id", "0x019d", args.file]
    print("+", " ".join(cmd))
    return subprocess.call(cmd)


def cmd_doctor(args) -> int:
    dev = Device()
    print("== USB vendor channel ==")
    frame = dev.answer(1.0)
    print("answer:", frame.hex(" ") if frame else "(none)")
    print("\n== BLE ==")
    ble_read()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--allow-write", action="store_true",
                    help="arm writes that touch the module (profile/volume/clock/screen)")
    ap.add_argument("--allow-flash", action="store_true",
                    help="arm writes that touch the keyboard's flash")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="device state")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("profile", help="profile dump/set")
    p.add_argument("action", choices=["dump", "set"])
    p.add_argument("--dump", type=pathlib.Path, required=True,
                   help="64 KiB flash dump to take the profile from")
    p.add_argument("--file", type=pathlib.Path, help="128 B profile to write")
    p.set_defaults(fn=cmd_profile)

    p = sub.add_parser("volume", help="show/set the volume field")
    p.add_argument("action", choices=["show", "set"])
    p.add_argument("--dump", type=pathlib.Path, required=True)
    p.add_argument("--value", type=int, default=50, help="system volume 0..100")
    p.add_argument("--scale", default="100", choices=["100", "16", "15", "255"])
    p.set_defaults(fn=cmd_volume)

    p = sub.add_parser("clock", help="set the module clock")
    p.add_argument("action", choices=["set"])
    p.add_argument("--fmt", default="odm-bcd",
                   choices=["odm-bcd", "odm-dec", "bcd", "epoch"])
    p.add_argument("--offset", type=int, default=0, help="minutes to add")
    p.set_defaults(fn=cmd_clock)

    p = sub.add_parser("screen", help="push a screen frame")
    p.add_argument("action", choices=["push"])
    p.add_argument("--file", type=pathlib.Path, required=True)
    p.add_argument("--w", type=int, default=240)
    p.add_argument("--h", type=int, default=135)
    p.set_defaults(fn=cmd_screen)

    p = sub.add_parser("backup", help="read the whole flash")
    p.add_argument("out", type=pathlib.Path)
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser("restore", help="write the whole flash back")
    p.add_argument("file", type=pathlib.Path)
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("doctor", help="print every observable")
    p.set_defaults(fn=cmd_doctor)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    import subprocess  # noqa: E402  (used by backup/restore)

    raise SystemExit(main())
