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


def build_packet(pack: str, content: bytes, content_size: int) -> bytes:
    """Assemble the bytes to push into the record.

    odm        -- the vendor `xn` header + a 24 byte content (default)
    odm10      -- same, but contentSize = 10 (just the time, no padding)
    raw        -- no header at all, just the 10 time bytes
    dotmatrix  -- the vendor's dot-matrix variant: the payload starts 3A
    cmdprefix  -- the ODM command byte (0x34) in front of the time bytes
    """
    if pack == "raw":
        return bytes(content)
    if pack == "cmdprefix":
        return bytes([CMD_TEMPORARY_DATA]) + bytes(content)
    if pack == "dotmatrix":
        c = bytearray(content)
        c[0] = 0x3A
        return odm_packet(CMD_TEMPORARY_DATA, bytes(c), content_size)
    size = 10 if pack == "odm10" else content_size
    return odm_packet(CMD_TEMPORARY_DATA, content, size)


def time_content(now: dt.datetime, encode: str = "dec", weekday: str = "sun0") -> bytes:
    """5A 01 5A yy mm dd hh mi ss wd  (weekday 0 = Sunday).

    `encode` selects plain decimal (what the ODM frontend sends) or BCD,
    `weekday` selects 0 = Sunday (ODM) or 0 = Monday (C style).
    """
    wd = (now.weekday() + 1) % 7 if weekday == "sun0" else now.weekday()
    fields = [now.year % 100, now.month, now.day,
              now.hour, now.minute, now.second]
    if encode == "bcd":
        fields = [(v // 10) << 4 | (v % 10) for v in fields]
    return bytes([0x5A, 0x01, 0x5A] + fields + [wd])


def record(cmd: int, data: bytes = b"", at: int = 0, sub: int | None = None,
           sub_at: int | None = None, size: int = PAYLOAD) -> bytes:
    p = bytearray(size)
    p[0] = cmd
    if sub is not None:
        # record 0x03 sub-dispatch reads xdata[0x08F7] = payload[1],
        # record 0x05 picks its module command from xdata[0x08FA] = payload[4]
        p[1 if sub_at is None else sub_at] = sub & 0x07
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

# extra recipes: which module command carries the time, and how the content
# is shaped.  `sub` is the record 0x03 sub-dispatch (1..4) and `pack` says how
# the content is assembled.
RECIPES: dict[str, dict] = {
    "04raw":   {"rec": 0x04, "at": 7, "pack": "raw"},
    "05raw":   {"rec": 0x05, "at": 7, "sub": 0, "sub_at": 4, "pack": "raw"},
    "03s1raw": {"rec": 0x03, "at": 7, "sub": 1, "sub_at": 1, "pack": "raw"},
    "03s2raw": {"rec": 0x03, "at": 7, "sub": 2, "sub_at": 1, "pack": "raw"},
    "04dot":   {"rec": 0x04, "at": 7, "pack": "dotmatrix"},
    "04cmd":   {"rec": 0x04, "at": 7, "pack": "cmdprefix"},
    "05cmd":   {"rec": 0x05, "at": 7, "sub": 0, "sub_at": 4, "pack": "cmdprefix"},
    "04odm":   {"rec": 0x04, "at": 7, "pack": "odm"},
    "05odm":   {"rec": 0x05, "at": 7, "sub": 0, "sub_at": 4, "pack": "odm"},
    "03s1odm": {"rec": 0x03, "at": 7, "sub": 1, "sub_at": 1, "pack": "odm"},
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=sorted(LAYOUTS), action="append")
    ap.add_argument("--recipe", choices=sorted(RECIPES), action="append",
                    help="named content/channel recipes (see RECIPES)")
    ap.add_argument("--spec", action="append",
                    help="ad-hoc recipe 'rec:sub:pack' (e.g. 0x05:2:raw, 0x03:1:odm, "
                         "0x04::raw); sub is the record 0x03/0x05 sub-dispatch")
    ap.add_argument("--distinct", action="store_true",
                    help="give every recipe its own time (base + index minutes) "
                         "so the screen shows which one landed")
    ap.add_argument("--pack", choices=["odm", "odm10", "raw", "dotmatrix", "cmdprefix"],
                    default="odm", help="how the ODM packet is assembled")
    ap.add_argument("--time", help="target time 'YYYY-MM-DD HH:MM:SS' (default: now)")
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--content-size", type=lambda s: int(s, 0), default=CONTENT_SIZE)
    ap.add_argument("--encode", choices=["dec", "bcd"], default="dec",
                    help="decimal (ODM) or BCD time fields")
    ap.add_argument("--weekday", choices=["sun0", "mon0"], default="sun0",
                    help="weekday base: 0 = Sunday (ODM) or 0 = Monday")
    ap.add_argument("--no-last", action="store_true",
                    help="clear the isLast flag in the ODM header")
    ap.add_argument("--overlay", help="start:end -- overlay the time content into "
                                      "the built-in profile at every byte offset in "
                                      "the range and send it via record 0x04; the "
                                      "time is base+offset minutes so the screen "
                                      "shows which offset landed")
    ap.add_argument("--restore", action="store_true",
                    help="send the built-in profile (flash 0x9983) unchanged via "
                         "record 0x04 -- puts the LED/profile fields back")
    a = ap.parse_args(argv)

    if a.time:
        now = dt.datetime.strptime(a.time, "%Y-%m-%d %H:%M:%S")
    else:
        now = dt.datetime.now()

    content = time_content(now, a.encode, a.weekday)
    packet = build_packet(a.pack, content, a.content_size)
    if a.no_last and len(packet) >= 8 and packet[0] == 0xAA:
        packet = packet[:6] + bytes([0x00]) + packet[7:]
    print(f"目标时间 {now:%Y-%m-%d %H:%M:%S} (星期 {content[9]})")
    print(f"包 ({a.pack}, {len(packet)} B): " + " ".join(f"{b:02x}" for b in packet))
    print()

    dev = Device()
    fw_path = pathlib.Path(__file__).resolve().parent.parent / "firmware" / "YD-Y65S_full.bin"
    profile = bytearray(fw_path.read_bytes()[0x9983:0x9983 + 128])
    if a.restore:
        ok = dev.send(record(0x04, bytes(profile), at=7))
        replies = dev.drain(2.0)
        print(f"restore: 内置 profile 原样下发 write={'ok' if ok else 'FAIL'} "
              f"reply={' '.join(f'{b:02x}' for b in replies[0]) if replies else '(none)'}")
        return 0

    if a.overlay:
        lo, hi = (int(x, 0) for x in a.overlay.split(":"))
        for k in range(lo, hi):
            when = now + dt.timedelta(minutes=k)
            body = bytearray(profile)
            content = time_content(when, a.encode, a.weekday)
            body[k:k + len(content)] = content
            payload = record(0x04, bytes(body), at=7)
            ok = dev.send(payload)
            replies = dev.drain(a.pause)
            frame = replies[0] if replies else b""
            print(f"offset {k:3d}  time={when:%H:%M:%S}  write={'ok' if ok else 'FAIL'}  "
                  f"reply={' '.join(f'{b:02x}' for b in frame) if frame else '(none)'}")
            time.sleep(0.2)
        return 0

    jobs: list[tuple[str, int, int, int | None, int | None, str]] = []
    for name in (a.recipe or a.only or []):
        if name in RECIPES:
            r = RECIPES[name]
            jobs.append((name, r["rec"], r["at"], r.get("sub"), r.get("sub_at"),
                         a.pack if a.pack != "odm" else r.get("pack", "odm")))
        else:
            cmd, at = LAYOUTS[name]
            jobs.append((name, cmd, at, (0, 4) if cmd == 0x05 else (None, None), None,
                         a.pack))
    for spec in a.spec or []:
        parts = spec.split(":")
        rec = int(parts[0], 0)
        sub = int(parts[1], 0) if len(parts) > 1 and parts[1] else None
        pack = parts[2] if len(parts) > 2 and parts[2] else a.pack
        sub_at = 1 if rec == 0x03 else (4 if rec == 0x05 else None)
        jobs.append((spec, rec, 7, sub, sub_at, pack))

    for index, (name, cmd, at, sub, sub_at, pack) in enumerate(jobs):
        when = now + dt.timedelta(minutes=index) if a.distinct else now
        content = time_content(when, a.encode, a.weekday)
        packet = build_packet(pack, content, a.content_size)
        if a.no_last and len(packet) >= 8 and packet[0] == 0xAA:
            packet = packet[:6] + bytes([0x00]) + packet[7:]
        payload = record(cmd, packet, at=at, sub=sub, sub_at=sub_at)
        ok = dev.send(payload)
        replies = dev.drain(a.pause)
        frame = replies[0] if replies else b""
        aa = frame[3] if len(frame) > 3 else None
        print(f"{name:12s} rec 0x{cmd:02X} sub={sub} @payload[{at}] pack={pack:9s} "
              f"time={when:%H:%M:%S}  write={'ok' if ok else 'FAIL'}  "
              f"reply={' '.join(f'{b:02x}' for b in frame) if frame else '(none)'}  "
              f"module_0xAA={'YES' if aa == 1 else 'no'}")
        print(f"             bytes: " + " ".join(f"{b:02x}" for b in packet))
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
