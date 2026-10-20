#!/usr/bin/env -S uv run python
"""isp_try.py -- try every way to make the YD-Y65S jump into its ISP.

The app side checks the EP0 OUT buffer for the magic pair 05 75 (firmware
0x82DC/0x82E6) before it jumps to the bootloader (0xB0ED).  Which HID
collection carries report 5 is worth double checking, so this walks the
plausible combinations and watches for the re-enumeration into 0603:1020.

Nothing here writes flash: the only thing sent is the entry magic.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402


def collections():
    out = []
    for e in vh.enumerate_hid(overlapped=True):
        caps = e.get("caps")
        if not caps:
            continue
        out.append((e, caps))
    return out


def send(entry, payload: bytes, length: int) -> bool:
    buf = vh.ctypes.create_string_buffer(length)
    vh.ctypes.memmove(buf, payload, len(payload))
    return bool(vh.hid.HidD_SetFeature(entry["handle"], buf, length))


def isp_present() -> bool:
    for e in vh.enumerate_hid(overlapped=True):
        if e.get("vid") == 0x0603:
            return True
    return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=4.0)
    a = ap.parse_args(argv)

    app = [(e, c) for e, c in collections()
           if e.get("vid") == 0x258A and e.get("pid") == 0x019D]
    print("258a:019d collections:")
    for e, c in app:
        print(f"   page={c.UsagePage:#06x} usage={c.Usage:#06x} "
              f"feat={c.FeatureReportByteLength} in={c.InputReportByteLength}")

    tries = []
    for e, c in app:
        if c.UsagePage != 0xFF00:
            continue
        flen = c.FeatureReportByteLength
        # 1) short magic packet, exact report length
        tries.append((f"page={c.UsagePage:#06x} len={flen} payload 6B",
                      e, bytes([0x05, 0x75, 0, 0, 0, 0]), flen))
        # 2) same but padded to the collection's feature length
        if flen > 6:
            tries.append((f"page={c.UsagePage:#06x} len={flen} payload padded",
                          e, bytes([0x05, 0x75]) + bytes(flen - 2), flen))
        # 3) magic duplicated in case the report id is not the first byte
        tries.append((f"page={c.UsagePage:#06x} len={flen} payload 05 05 75",
                      e, bytes([0x05, 0x05, 0x75]) + bytes(max(0, flen - 3)), flen))

    for name, e, payload, length in tries:
        if isp_present():
            print("!! 已经进了 ISP，停止")
            return 0
        ok = send(e, payload, length)
        time.sleep(a.wait)
        print(f"{name:52s} send={'ok' if ok else 'FAIL'} "
              f"isp_now={isp_present()}")
        if isp_present():
            print("进了 ISP！")
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
