#!/usr/bin/env -S uv run python
"""probe_records.py -- what does the keyboard answer on the vendor HID channel?

Every feature-9 record the firmware handles produces one short input report
on the same collection (report id 9, 7 payload bytes).  This tool sends a
matrix of records and prints the answer of each one, so the reply format can
be decoded from behaviour instead of guesswork.

Nothing here touches flash; only the record dispatchers run.

Usage
-----
    uv run tools/probe_records.py
    uv run tools/probe_records.py --repeat 2
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

VID, PID, PAGE, USAGE = 0x258A, 0x019D, 0xFF02, 0x0002
REPORT = 9
PAYLOAD = 519


class Device:
    def __init__(self) -> None:
        args = types.SimpleNamespace(vid=VID, pid=PID, page=PAGE, usage=USAGE)
        e = vh.pick(vh.enumerate_hid(overlapped=True), args)
        vh.guard(e, REPORT)
        self.handle = e["handle"]
        self.length = max(e["caps"].FeatureReportByteLength, REPORT + 1)
        self.in_len = max(e["caps"].InputReportByteLength if e["caps"] else 64, 64)
        self.event = vh.kernel32.CreateEventW(None, True, False, None)

    def send(self, payload: bytes) -> bool:
        buf = vh.ctypes.create_string_buffer(self.length)
        buf[0] = bytes([REPORT])
        buf[1:1 + len(payload)] = bytes(payload)
        return bool(vh.hid.HidD_SetFeature(self.handle, buf, self.length))

    def drain(self, seconds: float) -> list[bytes]:
        out: list[bytes] = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            buf = vh.ctypes.create_string_buffer(self.in_len)
            read = vh.wintypes.DWORD()
            vh.kernel32.ResetEvent(self.event)
            ov = vh.OVERLAPPED()
            ov.hEvent = self.event
            ok = vh.kernel32.ReadFile(self.handle, buf, self.in_len,
                                      vh.ctypes.byref(read), vh.ctypes.byref(ov))
            if not ok:
                if vh.ctypes.get_last_error() != 997:
                    time.sleep(0.01)
                    continue
                if vh.kernel32.WaitForSingleObject(self.event, 200) != 0:
                    vh.kernel32.CancelIo(self.handle)
                    continue
                vh.kernel32.GetOverlappedResult(self.handle, vh.ctypes.byref(ov),
                                                vh.ctypes.byref(read), False)
            if read.value:
                out.append(bytes(buf.raw[:read.value]))
        return out


def rec(cmd: int, data: bytes = b"", sub: int | None = None, at: int = 7,
        size: int = PAYLOAD) -> bytes:
    p = bytearray(size)
    p[0] = cmd
    if sub is not None:
        # record 0x03 sub-dispatch reads xdata[0x08F7] = payload[1],
        # record 0x05 picks its module command from xdata[0x08FA] = payload[4]
        p[1 if cmd == 0x03 else 4] = sub & 0x07
    if at:
        p[at:at + len(data)] = bytes(data)
    else:
        p[0:len(data)] = bytes(data)
    return bytes(p)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--pause", type=float, default=1.2)
    ap.add_argument("--mode", choices=["matrix", "idle", "single", "watchall", "profile"],
                    default="matrix",
                    help="idle = only listen, single = one record then a long listen")
    ap.add_argument("--cmd", type=lambda s: int(s, 0), default=0x04)
    ap.add_argument("--sub", type=int, default=None)
    ap.add_argument("--window", type=int, default=128)
    ap.add_argument("--idle-pause", type=float, default=1.5)
    a = ap.parse_args(argv)

    dev = Device()

    if a.mode == "idle":
        replies = dev.drain(a.pause)
        print(f"idle {a.pause:.1f}s: {len(replies)} replies")
        for r in replies:
            print("   " + " ".join(f"{b:02x}" for b in r))
        return 0

    if a.mode == "watchall":
        # listen on every collection of the device that can still be opened
        entries = vh.enumerate_hid(overlapped=True)
        args = types.SimpleNamespace(vid=VID, pid=PID, page=PAGE, usage=USAGE)
        targets = [e for e in entries
                   if e.get("vid") == VID and e.get("pid") == PID]
        for e in targets:
            caps = e.get("caps")
            e["in_len"] = max(caps.InputReportByteLength if caps else 64, 64)
            e["event"] = vh.kernel32.CreateEventW(None, True, False, None)
            print(f"open: usagePage={caps.UsagePage:#06x} usage={caps.Usage:#06x} "
                  f"in={e['in_len']}")
        deadline = time.time() + a.pause
        while time.time() < deadline:
            for e in targets:
                buf = vh.ctypes.create_string_buffer(e["in_len"])
                read = vh.wintypes.DWORD()
                vh.kernel32.ResetEvent(e["event"])
                ov = vh.OVERLAPPED()
                ov.hEvent = e["event"]
                ok = vh.kernel32.ReadFile(e["handle"], buf, e["in_len"],
                                          vh.ctypes.byref(read), vh.ctypes.byref(ov))
                if not ok:
                    if vh.ctypes.get_last_error() != 997:
                        continue
                    if vh.kernel32.WaitForSingleObject(e["event"], 50) != 0:
                        vh.kernel32.CancelIo(e["handle"])
                        continue
                    vh.kernel32.GetOverlappedResult(e["handle"], vh.ctypes.byref(ov),
                                                    vh.ctypes.byref(read), False)
                if read.value:
                    print(f"  +{time.time() - (deadline - a.pause):5.2f}s "
                          + " ".join(f"{b:02x}" for b in buf.raw[:read.value]), flush=True)
        return 0

    if a.mode == "profile":
        # exactly the 128 B block the firmware itself sends to the module at
        # boot (flash 0x9983) -- the least surprising thing to put on the wire
        fw = pathlib.Path(__file__).resolve().parent.parent / "firmware" / "YD-Y65S_full.bin"
        blob = fw.read_bytes()[0x9983:0x9983 + 128]
        payload = rec(0x04, blob, at=7)
        t0 = time.time()
        ok = dev.send(payload)
        replies = dev.drain(a.pause)
        print(f"built-in profile sent write={'ok' if ok else 'FAIL'} "
              f"{len(replies)} replies in {a.pause:.1f}s")
        for r in replies:
            print(f"   +{time.time() - t0:5.2f}s " + " ".join(f"{b:02x}" for b in r))
        return 0

    if a.mode == "single":
        data = bytes(a.window)
        payload = rec(a.cmd, data, sub=a.sub)
        t0 = time.time()
        ok = dev.send(payload)
        replies = dev.drain(a.pause)
        print(f"sent 0x{a.cmd:02X} sub={a.sub} write={'ok' if ok else 'FAIL'} "
              f"{len(replies)} replies in {a.pause:.1f}s")
        for r in replies:
            print(f"   +{time.time() - t0:5.2f}s " + " ".join(f"{b:02x}" for b in r))
        idle = dev.drain(a.idle_pause)
        print(f"idle {a.idle_pause:.1f}s after: {len(idle)} replies")
        for r in idle:
            print(f"   +{time.time() - t0:5.2f}s " + " ".join(f"{b:02x}" for b in r))
        return 0

    cases: list[tuple[str, bytes]] = []
    for sub in (1, 2, 3, 4):
        cases.append((f"record 0x03 sub={sub}", rec(0x03, sub=sub)))
    cases.append(("record 0x04 (128 B window, zeros)", rec(0x04, bytes(128))))
    cases.append(("record 0x05 sub=0 (512 B window, zeros)", rec(0x05, bytes(512), sub=0)))
    cases.append(("record 0x06", rec(0x06, bytes(128))))
    cases.append(("record 0x07 (ignored)", rec(0x07, bytes(8))))
    cases.append(("record 0x08", rec(0x08, bytes(8))))
    cases.append(("record 0x09 (ignored)", rec(0x09, bytes(8))))
    cases.append(("record 0x0A", rec(0x0A, bytes(8))))
    cases.append(("record 0x0E (ignored)", rec(0x0E, bytes(8))))

    for _ in range(a.repeat):
        for name, payload in cases:
            ok = dev.send(payload)
            replies = dev.drain(a.pause)
            head = " ".join(f"{b:02x}" for b in (replies[0] if replies else b""))
            print(f"{name:42s} write={'ok' if ok else 'FAIL'} "
                  f"replies={len(replies)} first=[{head}]", flush=True)
            time.sleep(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
