#!/usr/bin/env -S uv run python
"""isp_reboot.py -- reboot the YD-Y65S without touching the keyboard.

The vendor app can be wedged by a bad record (a corrupted RAM table or a
module session that never returns) while USB control transfers still work.
A plain power cycle fixes it, but the board may be out of reach, so this
drives the same reset the vendor tools use:

    app mode  : SetFeature(report 5, 05 75 00 00 00 00)  -> jump to the ISP
                (firmware stub 0xB0ED: MOV B,#0A5 / MOV A,#5A / LJMP 0FF00)
    ISP mode  : SetFeature(report 5, 05 5A 00 00 00 00)  -> bootloader
                reboots into the application (0xFF00: XRL A,#5A / XRL B,#A5)

No flash erase or write happens on either side: the ISP is only entered and
immediately asked to jump back to the application.

Usage
-----
    uv run tools/isp_reboot.py
    uv run tools/isp_reboot.py --enter-only
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

APP_VID, APP_PID = 0x258A, 0x019D
ISP_VID = 0x0603
ISP_PIDS = (0x1020, 0x1021)
REPORT = 5                      # the 5 byte command channel (usage page 0xff00)
ENTER_ISP = bytes([0x05, 0x75, 0x00, 0x00, 0x00, 0x00])
BACK_TO_APP = bytes([0x05, 0x5A, 0x00, 0x00, 0x00, 0x00])


def find(entries, vid, pid, page=0xFF00, usage=0x0001, feature=None, exact=False):
    """Return the first collection that matches the filter.

    `exact=True` matches the feature report length exactly (the 5 byte
    command channel lives in the collection whose longest feature report is
    6 bytes; the 1032 byte one is the flash page channel).
    """
    fallback = None
    for e in entries:
        if e.get("vid") != vid or e.get("pid") != pid:
            continue
        caps = e.get("caps")
        if caps is None:
            continue
        if page is not None and caps.UsagePage != page:
            continue
        if usage is not None and caps.Usage != usage:
            continue
        if feature is not None:
            if exact:
                if caps.FeatureReportByteLength == feature:
                    return e
                if caps.FeatureReportByteLength >= feature and fallback is None:
                    fallback = e
                continue
            if caps.FeatureReportByteLength < feature:
                continue
        return e
    return fallback


def set_feature(entry, payload: bytes) -> bool:
    """Send a feature report.  `payload` already carries the report id."""
    length = max(entry["caps"].FeatureReportByteLength, len(payload))
    buf = vh.ctypes.create_string_buffer(length)
    vh.ctypes.memmove(buf, bytes(payload), len(payload))
    return bool(vh.hid.HidD_SetFeature(entry["handle"], buf, length))


def show(tag: str, entries) -> None:
    for e in entries:
        caps = e.get("caps")
        if caps is None:
            continue
        print(f"  {tag}: {e.get('product', '')!r:22s} vid={e['vid']:04x} pid={e['pid']:04x} "
              f"page={caps.UsagePage:#06x} usage={caps.Usage:#06x} "
              f"feat={caps.FeatureReportByteLength} in={caps.InputReportByteLength}")


def isp_present() -> bool:
    for e in vh.enumerate_hid(overlapped=True):
        if e.get("vid") == 0x0603:
            return True
    return False


def app_present() -> bool:
    for e in vh.enumerate_hid(overlapped=True):
        if e.get("vid") == 0x258A:
            return True
    return False


def enter_isp(retries: int, wait: float) -> bool:
    """Send the entry magic until the board shows up as 0603:1020."""
    for attempt in range(1, retries + 1):
        entries = vh.enumerate_hid(overlapped=True)
        cmd_col = find(entries, APP_VID, APP_PID, feature=6, exact=True)
        if cmd_col is None:
            cmd_col = find(entries, APP_VID, APP_PID, feature=6)
        if cmd_col is None:
            print(f"  attempt {attempt}: 找不到 258a:019d 的 0xff00 命令集合")
            time.sleep(wait)
            continue
        ok = set_feature(cmd_col, ENTER_ISP)
        time.sleep(wait)
        if isp_present():
            # the transfer is cut short by the jump, so HidD_SetFeature may
            # report failure even though the jump happened
            print(f"  attempt {attempt}: 进入 ISP (SetFeature 返回 {'ok' if ok else 'FALSE'})")
            return True
        print(f"  attempt {attempt}: 未进入 ISP (SetFeature 返回 "
              f"{'ok' if ok else 'FALSE'})")
    return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--enter-only", action="store_true",
                    help="only enter the ISP, do not send the reboot command")
    ap.add_argument("--wait", type=float, default=6.0,
                    help="seconds to wait for the re-enumeration")
    ap.add_argument("--retries", type=int, default=5)
    a = ap.parse_args(argv)

    print("== app mode ==")
    entries = vh.enumerate_hid(overlapped=True)
    show("dev", entries)
    if a.enter_only:
        print("== 进入 ISP ==")
        if not enter_isp(a.retries, max(1.0, a.wait / 2)):
            print("!! 没进 ISP")
            return 1
        entries = vh.enumerate_hid(overlapped=True)
        show("dev", entries)
        return 0

    print("== 进入 ISP ==")
    if not enter_isp(a.retries, max(1.0, a.wait / 2)):
        print("!! 没进 ISP")
        return 1

    time.sleep(a.wait)
    print("== after jump ==")
    entries = vh.enumerate_hid(overlapped=True)
    show("dev", entries)
    if a.enter_only:
        return 0

    isp_col = None
    for pid in ISP_PIDS:
        isp_col = find(entries, ISP_VID, pid, feature=6, exact=True)
        if isp_col is not None:
            break
    if isp_col is None:
        for pid in ISP_PIDS:
            isp_col = find(entries, ISP_VID, pid, feature=6)
            if isp_col is not None:
                break
    if isp_col is None:
        # fall back: any 0603 collection that can carry a 6 byte feature report
        for e in entries:
            caps = e.get("caps")
            if e.get("vid") == ISP_VID and caps and caps.FeatureReportByteLength >= 6:
                isp_col = e
                break
    if isp_col is None:
        print("没有找到 0603:1020/1021 的 ISP 命令集合 —— 设备可能没进 ISP")
        return 2

    ok = set_feature(isp_col, BACK_TO_APP)
    print(f"reboot to app (report 5 = 05 5a 00 00 00 00): {'ok' if ok else 'FAILED'}")

    time.sleep(a.wait)
    print("== back in app mode ==")
    entries = vh.enumerate_hid(overlapped=True)
    show("dev", entries)
    back = find(entries, APP_VID, APP_PID, feature=6)
    print("app mode reachable again" if back else "!! 设备没有回到 258a:019d")
    return 0 if back else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
