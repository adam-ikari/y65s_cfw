#!/usr/bin/env python
"""watch_keys.py -- log the YD-Y65S input reports of both keyboard interfaces.

Pure read: it only calls ReadFile on the two input collections (boot keyboard
IF0 and the vendor interface IF1) and appends every report to a log file, so
we can see exactly what the keyboard sends for a given key.

Usage:
    uv run tools/watch_keys.py --seconds 90 --out keys.log
"""

from __future__ import annotations

import argparse
import ctypes
import pathlib
import sys
import time
from ctypes import wintypes

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

WAIT_TIMEOUT = vh.WAIT_TIMEOUT
ERROR_IO_PENDING = vh.ERROR_IO_PENDING


def open_input(vid: int, pid: int, page: int, usage: int):
    for e in vh.enumerate_hid(overlapped=True):
        caps = e.get("caps")
        if caps is None:
            continue
        if e.get("vid") == vid and e.get("pid") == pid \
                and caps.UsagePage == page and caps.Usage == usage:
            return e
    return None


def open_all_inputs():
    """Every HID collection that can deliver input reports."""
    out = []
    for e in vh.enumerate_hid(overlapped=True):
        caps = e.get("caps")
        if caps is None or not caps.InputReportByteLength:
            continue
        out.append(e)
    return out


def watch(entry, tag: str, deadline: float, log):
    caps = entry["caps"]
    length = max(caps.InputReportByteLength or 64, 64)
    event = vh.kernel32.CreateEventW(None, True, False, None)
    pending = False
    buf = read = ol = None
    while time.time() < deadline:
        if not pending:
            buf = ctypes.create_string_buffer(length)
            read = wintypes.DWORD()
            ol = vh.OVERLAPPED()
            ol.hEvent = event
            ok = vh.kernel32.ReadFile(entry["handle"], buf, length,
                                     ctypes.byref(read), ctypes.byref(ol))
            if ok:
                pending = False
            else:
                err = ctypes.get_last_error()
                if err != ERROR_IO_PENDING:
                    log.write(f"{tag} ReadFile failed: {err}\n")
                    log.flush()
                    break
                pending = True
        if pending:
            # Wait on the *same* event: issuing a second ReadFile while one is
            # pending orphans the first completion and loses every report.
            r = vh.kernel32.WaitForSingleObject(event, 1000)
            if r == WAIT_TIMEOUT:
                continue
            if not vh.kernel32.GetOverlappedResult(entry["handle"],
                                                   ctypes.byref(ol),
                                                   ctypes.byref(read), False):
                pending = False
                continue
            pending = False
        if read.value == 0:
            continue
        raw = buf.raw[: read.value]
        log.write(f"[{time.strftime('%H:%M:%S')}] {tag} id={raw[0]} len={len(raw)}: "
                  + " ".join(f"{b:02x}" for b in raw) + "\n")
        log.flush()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--out", default="keys.log")
    ap.add_argument("--all", action="store_true",
                    help="监听所有有 input report 的 HID 集合")
    args = ap.parse_args(argv)

    if args.all:
        targets = [(f"{e['vid']:04x}:{e['pid']:04x} "
                    f"p{e['caps'].UsagePage:04x}u{e['caps'].Usage:04x} ", e)
                   for e in open_all_inputs()]
    else:
        targets = [
            ("boot ", open_input(0x258A, 0x019D, 0x0001, 0x0080)),
            ("vendor", open_input(0x258A, 0x019D, 0xFF02, 0x0002)),
        ]
    open_ok = [t for t in targets if t[1] is not None]
    if not open_ok:
        print("没有找到键盘的输入集合")
        return 1
    print("监听: " + ", ".join(t[0] for t in open_ok), flush=True)

    deadline = time.time() + args.seconds
    with open(args.out, "w", encoding="utf-8") as log:
        log.write(f"# 开始 {time.strftime('%H:%M:%S')}\n")
        log.flush()
        # One reader per collection: both reads block until a report arrives,
        # so they have to run in threads.
        import threading
        threads = []
        for tag, entry in open_ok:
            t = threading.Thread(target=watch, args=(entry, tag, deadline, log))
            t.daemon = True
            t.start()
            threads.append(t)
        for t in threads:
            t.join(max(0.0, deadline - time.time()))
    print(f"日志: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
