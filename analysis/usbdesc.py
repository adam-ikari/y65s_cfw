#!/usr/bin/env -S uv run python
"""usbdesc.py — parse the USB device/config/string/HID-report descriptors that
are embedded verbatim in the YD-Y65S firmware image.

Usage:
  uv run analysis/usbdesc.py firmware/YD-Y65S_firmware.bin --dev 0x4698
  uv run analysis/usbdesc.py firmware/YD-Y65S_firmware.bin --hid 0x45B7 --len 0x130
  uv run analysis/usbdesc.py firmware/YD-Y65S_firmware.bin --all
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

# --------------------------------------------------------------------------
# HID report-descriptor item parser
# --------------------------------------------------------------------------

USAGE_PAGES = {
    0x01: "Generic Desktop",
    0x02: "Simulation",
    0x03: "VR",
    0x04: "Sport",
    0x05: "Game",
    0x06: "Generic Device",
    0x07: "Keyboard/Keypad",
    0x08: "LED",
    0x09: "Button",
    0x0A: "Ordinal",
    0x0B: "Telephony",
    0x0C: "Consumer",
    0x0D: "Digitizer",
    0x0F: "PID",
    0x10: "Unicode",
    0xFF00: "Vendor 0xFF00",
    0xFF01: "Vendor 0xFF01",
    0xFF02: "Vendor 0xFF02",
}

GD = {
    0x30: "X", 0x31: "Y", 0x32: "Z", 0x38: "Wheel", 0x80: "SystemControl",
    0x81: "SystemPowerDown", 0x82: "SystemSleep", 0x83: "SystemWake",
}
CONSUMER = {0x01: "ConsumerControl"}

MAIN = {0x80: "Input", 0x90: "Output", 0xB0: "Feature", 0xA0: "Collection", 0xC0: "EndCollection"}
COLLECTION = {
    0x00: "Physical", 0x01: "Application", 0x02: "Logical", 0x03: "Report",
    0x04: "NamedArray", 0x05: "UsageSwitch", 0x06: "UsageModifier",
}
GLOBAL = {
    0x00: "UsagePage", 0x10: "LogicalMin", 0x20: "LogicalMax", 0x30: "PhysicalMin",
    0x40: "PhysicalMax", 0x50: "UnitExponent", 0x60: "Unit", 0x70: "ReportSize",
    0x80: "ReportID", 0x90: "ReportCount", 0xA0: "Push", 0xB0: "Pop",
}
LOCAL = {0x00: "Usage", 0x10: "UsageMin", 0x20: "UsageMax", 0x30: "Designator",
         0x40: "DesignatorMin", 0x50: "DesignatorMax", 0x70: "StringIndex"}


def _signed(v: int, nbytes: int) -> int:
    bits = nbytes * 8
    if v & (1 << (bits - 1)):
        return v - (1 << bits)
    return v


def parse_hid(data: bytes) -> None:
    """Print a report descriptor as a structured tree."""
    i = 0
    glob = {"UsagePage": 0, "ReportSize": 0, "ReportCount": 0, "ReportID": None,
            "LogicalMin": 0, "LogicalMax": 0}
    stack: list[dict] = []
    usage_page = 0
    usages: list[int] = []
    depth = 0
    in_len: dict[int, int] = {}

    while i < len(data):
        b = data[i]
        i += 1
        if b == 0xFE:                                  # long item
            size, tag = data[i], data[i + 1]
            i += 2 + size
            continue
        size = b & 0x03
        size = 4 if size == 3 else size
        typ = (b >> 2) & 0x03
        tag = b & 0xF0
        raw = data[i:i + size]
        i += size
        val = int.from_bytes(raw, "little") if raw else 0

        if typ == 0:                                    # main
            name = MAIN.get(tag, f"Main{tag:02X}")
            if name == "Collection":
                cname = COLLECTION.get(val, f"Coll{val}")
                u = usages[0] if usages else None
                ul = usages[1] if len(usages) > 1 else None
                label = _usage_label(usage_page, u)
                extra = f" ({_usage_label(usage_page, ul)})" if ul is not None else ""
                rid = f" id={glob['ReportID']}" if glob["ReportID"] is not None else ""
                print(f"{'  '*depth}COLLECTION {cname}: {label}{extra}{rid}")
                stack.append(dict(glob))
                depth += 1
            elif name == "EndCollection":
                depth -= 1
                if stack:
                    glob = stack.pop()
            else:
                rid = f" id={glob['ReportID']}" if glob["ReportID"] is not None else ""
                bits = glob["ReportSize"] * glob["ReportCount"]
                u = usages[0] if usages else None
                label = _usage_label(usage_page, u) if u is not None else "-"
                rng = ""
                if len(usages) >= 2:
                    rng = f"{_usage_label(usage_page, usages[0])}..{_usage_label(usage_page, usages[-1])}"
                print(f"{'  '*depth}{name:<8} {bits:>4}b ({glob['ReportCount']}x{glob['ReportSize']})"
                      f" log[{glob['LogicalMin']}..{glob['LogicalMax']}]{rid} {rng or label}")
            usages.clear()
        elif typ == 1:                                  # global
            name = GLOBAL.get(tag, f"Global{tag:02X}")
            glob[name] = _signed(val, size) if name in ("LogicalMin", "LogicalMax") else val
            if name == "UsagePage":
                usage_page = val
            if name in ("Push", "Pop"):
                pass
        else:                                           # local
            name = LOCAL.get(tag, f"Local{tag:02X}")
            if name in ("Usage", "UsageMin", "UsageMax"):
                usages.append(val)


def _usage_label(page: int, usage: int | None) -> str:
    if usage is None:
        return "-"
    pname = USAGE_PAGES.get(page, f"page 0x{page:04X}")
    if page == 0x01:
        return f"{pname}:{GD.get(usage, hex(usage))}"
    if page == 0x07:
        return f"Keyboard:{_key_name(usage)}"
    if page == 0x0C:
        return f"Consumer:0x{usage:02X}"
    if page == 0x08:
        return f"LED:0x{usage:02X}"
    return f"{pname}:0x{usage:02X}"


def _key_name(u: int) -> str:
    special = {0x00: "Reserved", 0xE0: "LCtrl", 0xE1: "LShift", 0xE2: "LAlt", 0xE3: "LGUI",
               0xE4: "RCtrl", 0xE5: "RShift", 0xE6: "RAlt", 0xE7: "RGUI"}
    return special.get(u, f"0x{u:02X}")


# --------------------------------------------------------------------------
# Standard descriptors
# --------------------------------------------------------------------------

def parse_device(data: bytes, off: int) -> int:
    b = data[off:off + data[off]]
    if len(b) < 18 or b[1] != 1:
        print(f"  0x{off:04X}: not a device descriptor")
        return off + 18
    (blen, dtype, bcd_usb, cls, sub, proto, mps, vid, pid, bcd_dev, iman, iprod,
     iser, ncfg) = struct.unpack("<BBHBBBBHHHBBBB", b[:18])
    print(f"  0x{off:04X}  DEVICE   bcdUSB=0x{bcd_usb:04X} class={cls:#04x} sub={sub} proto={proto} "
          f"mps={mps} VID:PID={vid:04X}:{pid:04X} bcdDevice=0x{bcd_dev:04X} "
          f"iMan={iman} iProd={iprod} iSer={iser} cfgs={ncfg}")
    return off + blen


def parse_config(data: bytes, off: int) -> int:
    blen = data[off]
    total = struct.unpack("<H", data[off + 2:off + 4])[0]
    print(f"  0x{off:04X}  CONFIG   total={total} ifaces={data[off+4]} value={data[off+5]} "
          f"attrs=0x{data[off+7]:02X} maxpow={data[off+8]*2}mA")
    i = off + blen
    end = off + total
    while i < end:
        ln = data[i]
        if ln == 0:
            break
        t = data[i + 1]
        if t == 4:  # interface
            print(f"  0x{i:04X}    IFACE {data[i+2]} alt={data[i+3]} "
                  f"eps={data[i+4]} class=0x{data[i+5]:02X} sub={data[i+6]} proto={data[i+7]}")
        elif t == 5:  # endpoint
            print(f"  0x{i:04X}    EP    0x{data[i+2]:02X} attrs=0x{data[i+3]:02X} "
                  f"maxpkt={struct.unpack('<H', data[i+4:i+6])[0]} interval={data[i+6]}")
        elif t == 0x21:  # HID
            n = data[i + 5]
            subs = ",".join(f"type{data[i+6+2*k]:#04x}/len0x{struct.unpack('<H', data[i+7+2*k:i+9+2*k])[0]:X}"
                            for k in range(n))
            print(f"  0x{i:04X}    HID    bcdHID=0x{struct.unpack('<H', data[i+2:i+4])[0]:04X} "
                  f"country={data[i+4]} {subs}")
        else:
            print(f"  0x{i:04X}    type=0x{t:02X} len={ln}")
        i += ln
    return end


def parse_string(data: bytes, off: int) -> int:
    ln = data[off]
    t = data[off + 1]
    payload = data[off + 2:off + ln]
    if t == 3:
        s = payload.decode("utf-16-le", errors="replace")
        print(f"  0x{off:04X}  STRING   {ln:3d}B  {s!r}")
    else:
        print(f"  0x{off:04X}  type=0x{t:02X} len={ln}")
    return off + ln


def scan_strings(data: bytes, start: int = 0, end: int | None = None) -> None:
    end = len(data) if end is None else end
    print("string descriptors found in the image:")
    for off in range(start, end - 3):
        if data[off + 1] != 3 or data[off] < 4 or data[off] > 0xFF:
            continue
        ln = data[off]
        if off + ln > len(data) or ln % 2 == 0:
            continue
        payload = data[off + 2:off + ln]
        if len(payload) % 2:
            continue
        try:
            s = payload.decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        if s and all(0x20 <= ord(c) < 0x7F for c in s):
            print(f"  0x{off:04X}  {ln:3d}B  {s!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--dev", type=lambda s: int(s, 0), help="device descriptor offset")
    ap.add_argument("--hid", type=lambda s: int(s, 0), action="append", default=[],
                    help="HID report descriptor offset (repeatable)")
    ap.add_argument("--len", type=lambda s: int(s, 0), action="append", default=[],
                    help="length for the matching --hid")
    ap.add_argument("--strings", action="store_true")
    ap.add_argument("--string-range", help="start:end to scan for string descriptors, e.g. 0x4400:0x46A0")
    args = ap.parse_args()

    data = Path(args.file).read_bytes()

    if args.strings:
        s, e = 0, len(data)
        if args.string_range:
            a, b = args.string_range.split(":")
            s, e = int(a, 0), int(b, 0)
        scan_strings(data, s, e)
    if args.dev is not None:
        off = parse_device(data, args.dev)
        off = parse_config(data, off)
    for k, hoff in enumerate(args.hid):
        n = args.len[k] if k < len(args.len) else 0x200
        print(f"\n=== HID report descriptor @ 0x{hoff:04X} ({n} bytes) ===")
        parse_hid(data[hoff:hoff + n])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
