#!/usr/bin/env -S uv run python
"""tft_probe.py -- controlled experiments against the YD-Y65S screen / module link.

Everything here goes through the vendor HID channel that was reverse engineered
from the 8051 firmware:

    SetFeature(feature report 9, IF1, usage page 0xff02), 519-byte payload.

The firmware turns that payload into a "record" whose first byte selects a
handler (0x03..0x0E).  The handlers that matter for the screen:

    record 0x04  module cmd 0x52  forwards payload[7..134]  (128 B) byte by byte
    record 0x05  module cmd 0x6E+ payload[4]
                           forwards payload[7..518]  (512 B) byte by byte
    record 0x0B/0x0C/0x0D
                module cmd 0x81  forwards the whole 519 B payload as one bulk
                                 frame (50 81 02 08 + 520 B)

"Byte by byte" means the firmware emits one module frame per payload byte
(`50 <cmd> 01 <byte> <sum>`), so the module reassembles a *byte stream* -- an
ODM-style packet (AA <cmd> <len> <addr...> + data) can therefore be carried
inside one of these windows.

The ODM (driveall.cn) web driver was re-read to get the exact byte layouts used
by the vendor tooling; see the module-link brain page.  Short version:

    SET_TEMPORARY_COMMAND_DATA (52)  header AA 34 <len=contentSize> 00 00 00 01 00
                                      + 10 B time payload 5A 01 5A yy mm dd hh mi ss wd
    SET_TFT_USER_ANIMATION (80)      header AA 50 <idx_lo> <idx_hi> <total_lo>
                                           <total_hi> 50 06
                                      + (256 B delay table + RGB565LE pixels)
    SET_TFT_BUILT_IN_INDEX (81)       1 byte payload

Nothing here touches the keyboard flash; only the module's screen state and its
own user-animation area are affected.

Usage
-----
    uv run tools/tft_probe.py clock
    uv run tools/tft_probe.py native
    uv run tools/tft_probe.py builtin --index 0
    uv run tools/tft_probe.py tft --path 05 --w 135 --h 240
    uv run tools/tft_probe.py raw --file payload.bin
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import pathlib
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

VID, PID, PAGE, USAGE = 0x258A, 0x019D, 0xFF02, 0x0002
REPORT = 9
PAYLOAD = 519          # feature report 9 payload length (report id excluded)
WINDOW = 128           # record 0x04 data window: payload[7..134]
BLOCK = 512            # record 0x05 data window: payload[7..518]
DATA_OFF = 7           # first data byte inside the record payload
FIRMWARE = pathlib.Path(__file__).resolve().parent.parent / "firmware" / "YD-Y65S_full.bin"
BUILTIN_BLOB = 0x9983  # firmware code: 128 B built-in screen content


# --------------------------------------------------------------------------
# device plumbing
# --------------------------------------------------------------------------
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
        buf = ctypes.create_string_buffer(self.length)
        buf[0] = bytes([REPORT])
        buf[1:1 + len(payload)] = bytes(payload)
        return bool(vh.hid.HidD_SetFeature(self.handle, buf, self.length))

    def drain(self, seconds: float) -> list[bytes]:
        """Read whatever the keyboard sends back within `seconds`."""
        out: list[bytes] = []
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
                if ctypes.get_last_error() != 997:   # ERROR_IO_PENDING
                    time.sleep(0.01)
                    continue
                if vh.kernel32.WaitForSingleObject(self.event, 200) != 0:
                    vh.kernel32.CancelIo(self.handle)
                    continue
                vh.kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov),
                                                ctypes.byref(read), False)
            if read.value:
                out.append(bytes(buf.raw[:read.value]))
        return out


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def record(cmd: int, data: bytes = b"", at: int = DATA_OFF, sub: int | None = None,
           size: int = PAYLOAD) -> bytes:
    """Build one feature-9 record payload.

    `data` is placed at payload[at]; `sub` (if given) goes to payload[4] and
    selects the module command for record 0x05.
    """
    p = bytearray(size)
    p[0] = cmd
    if sub is not None:
        p[4] = sub & 0x07
    p[at:at + len(data)] = data[:max(0, size - at)]
    return bytes(p)


def rec_window(data: bytes, at: int = DATA_OFF) -> bytes:
    """Record 0x04 -- module cmd 0x52, 128 byte window."""
    return record(0x04, data[:WINDOW], at=at)


def rec_block(data: bytes, sub: int = 0, at: int = DATA_OFF) -> bytes:
    """Record 0x05 -- module cmd 0x6E+sub, 512 byte window."""
    return record(0x05, data[:BLOCK], at=at, sub=sub)


def rec_bulk(data: bytes, cmd: int = 0x0B, at: int = DATA_OFF) -> bytes:
    """Record 0x0B/0x0C/0x0D -- the whole payload is forwarded (module cmd 0x81)."""
    return record(cmd, data, at=at)


# --------------------------------------------------------------------------
# ODM packet builders (byte exact, re-derived from the vendor web driver)
# --------------------------------------------------------------------------
def odm_header(cmd: int, length: int) -> bytes:
    """AA <cmd> <len> <addr_lo> <addr_hi> 00 01 00  (the vendor `xn` builder).

    byte 2 is the *content size* of the command, byte 6 is the "last packet"
    flag, byte 5 and 7 are unused.
    """
    return bytes([0xAA, cmd & 0xFF, length & 0xFF, 0x00, 0x00, 0x00, 0x01, 0x00])


def tft_header(idx: int, total: int) -> bytes:
    """AA 50 <idx_lo> <idx_hi> <total_lo> <total_hi> 50 06 (custom header)."""
    return bytes([0xAA, 0x50, idx & 0xFF, (idx >> 8) & 0xFF,
                  total & 0xFF, (total >> 8) & 0xFF, 0x50, 0x06])


def time_payload(now: dt.datetime | None = None) -> bytes:
    """5A 01 5A yy mm dd hh mi ss wd  (vendor Hu)."""
    now = now or dt.datetime.now()
    wd = (now.weekday() + 1) % 7          # 0-6, Sunday = 0
    return bytes([0x5A, 0x01, 0x5A, now.year % 100, now.month, now.day,
                  now.hour, now.minute, now.second, wd])


def rgb565(r: int, g: int, b: int) -> bytes:
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | ((b & 0xF8) >> 3)
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


def test_pattern(w: int, h: int) -> bytes:
    """Four coloured quadrants, a crosshair and a white border.

    Deliberately asymmetric so rotation / mirroring is visible on the panel.
    """
    out = bytearray()
    border = max(2, min(w, h) // 40)
    for y in range(h):
        for x in range(w):
            if x < border or y < border or x >= w - border or y >= h - border:
                px = (255, 255, 255)
            elif abs(x - w // 2) <= 1 or abs(y - h // 2) <= 1:
                px = (0, 0, 0)
            elif x < w // 2 and y < h // 2:
                px = (255, 0, 0)
            elif x >= w // 2 and y < h // 2:
                px = (0, 255, 0)
            elif x < w // 2 and y >= h // 2:
                px = (0, 0, 255)
            else:
                px = (255, 255, 0)
            out += rgb565(*px)
    return bytes(out)


def tft_stream(w: int, h: int, frames: int = 1) -> bytes:
    """256 B delay table + RGB565 pixels, exactly like the vendor `zu`."""
    header = bytearray([0xFF] * 256)
    header[0] = frames
    header[frames] = 0
    return bytes(header) + test_pattern(w, h)


def builtin_blob() -> bytes:
    """The 128 byte screen-content blob that the firmware sends at session start."""
    return FIRMWARE.read_bytes()[BUILTIN_BLOB:BUILTIN_BLOB + WINDOW]


# --------------------------------------------------------------------------
# experiments
# --------------------------------------------------------------------------
def say(msg: str) -> None:
    print(msg, flush=True)


def show_replies(replies: list[bytes]) -> None:
    for r in replies:
        say("   IN: " + " ".join(f"{b:02x}" for b in r))
    if not replies:
        say("   IN: (nothing)")


def exp_clock(dev: Device, pause: float) -> int:
    """Find where the ODM time packet has to sit inside the 128 byte window."""
    now = dt.datetime.now()
    ts = time_payload(now)
    variants = [
        ("T1 ODM packet (len=0x18) at payload[7]",
         rec_window(odm_header(0x34, 0x18) + ts + bytes(14), at=DATA_OFF)),
        ("T2 ODM packet (len=0x0A) at payload[7]",
         rec_window(odm_header(0x34, 0x0A) + ts + bytes(14), at=DATA_OFF)),
        ("T3 raw 10 B payload at payload[7] (24 B padded)",
         rec_window(ts + bytes(14), at=DATA_OFF)),
        ("T4 ODM packet (len=0x18) at payload[0]",
         record(0x04, odm_header(0x34, 0x18) + ts + bytes(14), at=0)),
    ]
    say(f"校时实验: 目标时间 {now:%Y-%m-%d %H:%M:%S} (星期 {ts[9]})")
    say("屏幕若跳到该时间 -> 对应变体就是正确的窗口布局。")
    for name, payload in variants:
        say("")
        say(f"--- {name}")
        ok = dev.send(payload)
        say(f"    写入 {'成功' if ok else '失败'}")
        show_replies(dev.drain(pause))
        say(f"    （{pause:.0f}s 内观察屏幕时钟）")
        time.sleep(pause)
    return 0


def exp_native(dev: Device, pause: float) -> int:
    """Replay the firmware's built-in content blob, then patched variants."""
    blob = builtin_blob()
    variants = [
        ("N1 原样内置内容 (128 B)", blob),
        ("N2 尾部像素改成纯红", blob[:52] + rgb565(255, 0, 0) * 18 + blob[88:]),
        ("N3 尾部像素改成纯蓝", blob[:52] + rgb565(0, 0, 255) * 18 + blob[88:]),
        ("N4 尾部像素清零", blob[:52] + bytes(36) + blob[88:]),
    ]
    say("内置内容复现实验: N1 应当重现固件开机时的画面。")
    say("N2/N3/N4 若画面有变化 -> 128 B 窗口就是可自定义的屏幕内容通道。")
    for name, data in variants:
        say("")
        say(f"--- {name}")
        ok = dev.send(rec_window(data, at=DATA_OFF))
        say(f"    写入 {'成功' if ok else '失败'}")
        show_replies(dev.drain(pause))
        say(f"    （{pause:.0f}s 内观察屏幕）")
        time.sleep(pause)
    return 0


def exp_builtin(dev: Device, index: int, pause: float) -> int:
    """SET_TFT_BUILT_IN_INDEX (module cmd 0x6F) through both transports."""
    say(f"内置图索引实验: index={index}")
    for name, payload in [
        ("B1 record 0x05, 索引在 payload[7]（512 B 窗口）",
         rec_block(bytes([index]), sub=0x01, at=DATA_OFF)),
        ("B2 record 0x0B 批量通道, 索引在 payload[7]",
         rec_bulk(bytes([index]), cmd=0x0B, at=DATA_OFF)),
    ]:
        say("")
        say(f"--- {name}")
        ok = dev.send(payload)
        say(f"    写入 {'成功' if ok else '失败'}")
        show_replies(dev.drain(pause))
        say(f"    （{pause:.0f}s 内观察屏幕是否换图）")
        time.sleep(pause)
    return 0


def exp_tft(dev: Device, w: int, h: int, path: str, at: int, delay: float,
            limit: int) -> int:
    """Upload a test picture as an ODM SET_TFT_USER_ANIMATION packet stream."""
    stream = tft_stream(w, h)
    if path == "05":
        # the firmware hands the module exactly 512 B per record, so one ODM
        # packet is 8 B header + 504 B payload, whatever the placement is
        window = BLOCK
    else:
        # bulk path: the whole 519 B payload is forwarded (report id + 519),
        # so the packet is limited by the space left after `at`
        window = PAYLOAD - at
    data_per = window - 8
    total = (len(stream) + data_per - 1) // data_per
    say(f"TFT 上传: {w}x{h}  流 {len(stream)} B  {total} 包 x {data_per} B 数据"
        f"（包窗 {window} B，ODM 包放在 payload[{at}]）"
        f"路径 {'record 0x05' if path == '05' else 'record 0x0B 批量'}")
    for idx in range(min(total, limit)):
        piece = stream[idx * data_per:(idx + 1) * data_per]
        piece += bytes(data_per - len(piece))
        packet = tft_header(idx, total) + piece
        if path == "05":
            payload = rec_block(packet, sub=0x00, at=at)
        else:
            payload = rec_bulk(packet, cmd=0x0B, at=at)
        ok = dev.send(payload)
        if idx % 10 == 0 or idx == total - 1:
            say(f"    包 {idx + 1}/{total} 写入 {'成功' if ok else '失败'}")
        if not ok:
            return 1
        if idx != total - 1:
            time.sleep(delay)
    show_replies(dev.drain(2.0))
    say("上传结束，看屏幕是否出现四色 + 十字线测试图。")
    return 0


def exp_raw(dev: Device, data: bytes, at: int, cmd: int) -> int:
    payload = record(cmd, data, at=at)
    ok = dev.send(payload)
    say(f"记录 0x{cmd:02X} 写入({'成功' if ok else '失败'}) "
        f"{len(data)} B @ payload[{at}]")
    show_replies(dev.drain(2.0))
    return 0


# --------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("clock", help="校时布局矩阵 (record 0x04)")
    c.add_argument("--pause", type=float, default=4.0)

    n = sub.add_parser("native", help="内置 128 B 内容复现 / 改写 (record 0x04)")
    n.add_argument("--pause", type=float, default=4.0)

    b = sub.add_parser("builtin", help="切换内置图索引 (0x6F)")
    b.add_argument("--index", type=int, default=0)
    b.add_argument("--pause", type=float, default=3.0)

    t = sub.add_parser("tft", help="上传测试图 (ODM 0x50)")
    t.add_argument("--w", type=int, default=135)
    t.add_argument("--h", type=int, default=240)
    t.add_argument("--path", choices=["05", "81"], default="05",
                   help="05 = 记录 0x05 字节流(512 B 窗) / 81 = 记录 0x0B 批量(519 B 块)")
    t.add_argument("--at", type=int, default=None,
                   help="ODM 包在记录 payload 里的偏移 (默认 05->7, 81->1)")
    t.add_argument("--delay", type=float, default=1.8)
    t.add_argument("--limit", type=int, default=100000)

    r = sub.add_parser("raw", help="发送任意记录")
    r.add_argument("--cmd", type=lambda s: int(s, 0), default=0x04)
    r.add_argument("--file", required=True)
    r.add_argument("--at", type=int, default=DATA_OFF)

    a = ap.parse_args(argv)
    dev = Device()
    if a.cmd == "clock":
        return exp_clock(dev, a.pause)
    if a.cmd == "native":
        return exp_native(dev, a.pause)
    if a.cmd == "builtin":
        return exp_builtin(dev, a.index, a.pause)
    if a.cmd == "tft":
        at = a.at if a.at is not None else (DATA_OFF if a.path == "05" else 1)
        return exp_tft(dev, a.w, a.h, a.path, at, a.delay, a.limit)
    if a.cmd == "raw":
        data = pathlib.Path(a.file).read_bytes()
        return exp_raw(dev, data, a.at, a.cmd)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
