#!/usr/bin/env -S uv run python
"""clock_set.py -- set the module's screen clock and tell whether it landed.

The ODM reference frontend (build/odm/) calibrates the TFT time with
``cmd 52 = SET_TEMPORARY_COMMAND_DATA`` and builds the packet with ``xn``:

    header  AA <cmd> <contentSize> <addr_lo> <addr_hi> 00 <isLast> 00
    content 5A 01 5A yy mm dd hh mi ss wd  (+ zero padding)

``contentSize`` defaults to 24 in the vendor code, so the content is 24 bytes
even though the time itself is 10.  The packet is shipped inside the 520 byte
bulk frame (module command 0x81) that the firmware builds for records
0x0B / 0x0C / 0x0D -- the ODM packet therefore starts at payload[1] (byte 0
is the report id, byte 1 is the record command).

This tool sweeps the plausible placements and reports the device's answer
frame.  That frame is 8 bytes: ``09 0a 06 <aa> <counter> 00 00 00`` where the
4th byte is 1 only when the module answered 0xAA (firmware 0x9BA7 stores the
module's answer in [0x0D84]).  For the bulk records that flag is a usable
oracle: 1 = the module took the frame, 0 = it did not answer 0xAA.

Nothing here touches flash; only the module's screen state is affected.

Usage
-----
    uv run tools/clock_set.py                 # sweep every layout
    uv run tools/clock_set.py --only 0b1      # one layout
    uv run tools/clock_set.py --time "2026-10-20 20:45:00"
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

VID, PID, PAGE, USAGE = 0x258A, 0x019D, 0xFF02, 0x0002
REPORT = 9
PAYLOAD = 519
DATA_OFF = 7

CMD_TEMPORARY_DATA = 0x34        # ODM: 52
CONTENT_SIZE = 0x18              # vendor default: 24


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


def odm_packet(cmd: int, content: bytes, content_size: int = CONTENT_SIZE,
               addr: int = 0, is_last: bool = True) -> bytes:
    """Rebuild the vendor `xn` header byte for byte.

    AA | cmd | contentSize | addr_lo | addr_hi | 00 | isLast | 00 | data...
    """
    hdr = bytearray(8)
    hdr[0] = 0xAA
    hdr[1] = cmd & 0xFF
    hdr[2] = content_size & 0xFF
    hdr[3] = addr & 0xFF
    hdr[4] = (addr >> 8) & 0xFF
    hdr[6] = 1 if is_last else 0
    body = bytearray(content_size)
    body[:min(len(content), content_size)] = content[:content_size]
    return bytes(hdr) + bytes(body)


def time_content(now: dt.datetime) -> bytes:
    """5A 01 5A yy mm dd hh mi ss wd  (weekday 0 = Sunday)."""
    wd = (now.weekday() + 1) % 7
    return bytes([0x5A, 0x01, 0x5A, now.year % 100, now.month, now.day,
                  now.hour, now.minute, now.second, wd])


def record(cmd: int, data: bytes = b"", at: int = 0, sub: int | None = None,
           size: int = PAYLOAD) -> bytes:
    p = bytearray(size)
    p[0] = cmd
    if sub is not None:
        p[4] = sub & 0x07
    if at:
        p[at:at + len(data)] = bytes(data)
    else:
        p[0:len(data)] = bytes(data)
    return bytes(p)


# name -> (record command, offset of the ODM packet inside the payload)
LAYOUTS: dict[str, tuple[int, int]] = {
    "0b1": (0x0B, 1),      # bulk frame, ODM packet right after the record byte
    "0c1": (0x0C, 1),
    "0d1": (0x0D, 1),
    "0b7": (0x0B, 7),      # bulk frame, ODM packet at the usual data offset
    "047": (0x04, 7),     # 128 byte profile window
    "057": (0x05, 7),     # 512 byte window, module cmd 0x6E
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=sorted(LAYOUTS), action="append")
    ap.add_argument("--time", help="target time 'YYYY-MM-DD HH:MM:SS' (default: now)")
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--content-size", type=lambda s: int(s, 0), default=CONTENT_SIZE)
    a = ap.parse_args(argv)

    if a.time:
        now = dt.datetime.strptime(a.time, "%Y-%m-%d %H:%M:%S")
    else:
        now = dt.datetime.now()

    packet = odm_packet(CMD_TEMPORARY_DATA, time_content(now), a.content_size)
    print(f"目标时间 {now:%Y-%m-%d %H:%M:%S} (星期 {time_content(now)[9]})")
    print("ODM 包 (" + str(len(packet)) + " B): " + " ".join(f"{b:02x}" for b in packet))
    print()

    dev = Device()
    layouts = a.only or sorted(LAYOUTS)
    for name in layouts:
        cmd, at = LAYOUTS[name]
        sub = 0 if cmd == 0x05 else None
        payload = record(cmd, packet, at=at, sub=sub)
        t0 = time.time()
        ok = dev.send(payload)
        replies = dev.drain(a.pause)
        frame = replies[0] if replies else b""
        aa = frame[3] if len(frame) > 3 else None
        print(f"{name:5s} record 0x{cmd:02X} @payload[{at}]  write={'ok' if ok else 'FAIL'}  "
              f"reply={' '.join(f'{b:02x}' for b in frame) if frame else '(none)'}  "
              f"module_0xAA={'YES' if aa == 1 else 'no'}")
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
