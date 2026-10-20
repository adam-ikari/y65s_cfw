#!/usr/bin/env -S uv run python
"""isp_exit.py -- send the ISP's reboot command so the keyboard comes back.

While the board sits in the ISP it enumerates as 0603:1020/0603:1021 and the
keyboard does nothing.  Command 0x5A makes the bootloader jump back into the
application (bootloader 0xFF00: XRL A,#5A -> app entry), which is a plain
reboot: RAM is reloaded from flash, no flash is written.

Usage
-----
    uv run tools/isp_exit.py
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

ISP_VID = 0x0603
ISP_PIDS = (0x1020, 0x1021)
REPORT = 5


def list_devices():
    out = []
    for e in vh.enumerate_hid(overlapped=True):
        caps = e.get("caps")
        if caps is None:
            continue
        out.append((e, caps))
    return out


def send(entry, payload: bytes, length: int) -> bool:
    buf = vh.ctypes.create_string_buffer(length)
    vh.ctypes.memmove(buf, payload, len(payload))
    return bool(vh.hid.HidD_SetFeature(entry["handle"], buf, length))


def app_present() -> bool:
    return any(e.get("vid") == 0x258A for e in vh.enumerate_hid(overlapped=True))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=5.0)
    a = ap.parse_args(argv)

    print("== devices ==")
    for e, c in list_devices():
        print(f"  vid={e['vid']:04x} pid={e['pid']:04x} {e.get('product','')!r:20s} "
              f"page={c.UsagePage:#06x} usage={c.Usage:#06x} feat={c.FeatureReportByteLength}")

    targets = [(e, c) for e, c in list_devices()
               if e.get("vid") == ISP_VID and e.get("pid") in ISP_PIDS]
    if not targets:
        print("找不到 0603:1020/1021 —— 设备不在 ISP 里")
        return 1

    variants = [
        ("05 5a 00 00 00 00", bytes([0x05, 0x5A, 0x00, 0x00, 0x00, 0x00]), 6),
        ("05 5a 00 00 00 00 (padded to feature len)", None, None),
    ]

    for e, c in targets:
        flen = c.FeatureReportByteLength
        tries = [("05 5a + zero pad", bytes([0x05, 0x5A]) + bytes(max(0, flen - 2)), flen),
                 ("05 5a (6 bytes)", bytes([0x05, 0x5A, 0, 0, 0, 0]), 6)]
        for name, payload, length in tries:
            ok = send(e, payload, length)
            time.sleep(a.wait)
            back = app_present()
            print(f"  send {name:34s} len={length:5d} -> {'ok' if ok else 'FAIL'} "
                  f"app_back={back}")
            if back:
                print("== 键盘已回到应用模式 ==")
                return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
