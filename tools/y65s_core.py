#!/usr/bin/env -S uv run python
"""y65s_core.py -- device side of our own Y65S (258a:019d) tool.

USB only, cross platform (Windows / Linux / macOS) through tools/y65s_hid.py.

Transport
    feature report 9 on usage page 0xff02 / usage 0x0002, 519 byte payload.
    payload[0] = record command, payload[7] = first data byte.

Records
    0x03  sub-dispatch 1..4  -> module cmds 0x62 / 0x66 / 0x6A / 0x5E
    0x04  128 byte window     -> module cmd 0x52 (the device profile)
    0x05  512 byte window     -> module cmd 0x6E + payload[4]
    0x06  TFT mode setup      -> module cmd 0x56
    0x08  RAM config table    -> WRITES THE KEYBOARD'S FLASH: never use casually
    0x0A  fixed code table    -> module cmd 0x54
    0x0B/0x0C/0x0D 520 byte bulk frame -> module cmd 0x81 (screen content)

Profile (module cmd 0x52)
    128 bytes.  Factory copy at flash 0x9983, live copy at 0xA400.
    0x3A..0x7D are read by the module only, 0x7E/0x7F are the "initialised"
    marker 5A A5.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import struct
import time

import y65s_hid

REPORT = y65s_hid.REPORT
PAYLOAD = 519
DATA_OFF = 7

PROFILE_LEN = 128
FACTORY_PROFILE_OFF = 0x9983
LIVE_PROFILE_OFF = 0xA400
PROFILE_MARKER = bytes([0x5A, 0xA5])

# profile field -> (name, factory value)
PROFILE_FIELDS = {
    0x03: ("keymap_id", 0x00),
    0x0A: ("led_effect_index", 0x0B),
    0x16: ("reserved_16", 0x00),
    0x18: ("reserved_18", 0x99),
    0x1F: ("reserved_1F", 0x0A),
    0x31: ("volume_level", 0x64),
    0x33: ("led_effect_mode", 0x01),
    0x35: ("reserved_35", 0x01),
    0x36: ("reserved_36", 0x01),
    0x37: ("reserved_37", 0x00),
}

SCREEN_W, SCREEN_H = 240, 135
SCREEN_BLOCK = 512

# the vendor app's clock payload (see the module-link brain page):
#   [date][cpu][x] yy_lo yy_hi mo dd hh mi ss wd
CLOCK_PAYLOAD_LEN = 11


class Y65s:
    """The keyboard over the vendor HID channel."""

    def __init__(self, path: str | None = None) -> None:
        self.dev = y65s_hid.Device(path)
        self.backend = self.dev.backend

    # -- records ----------------------------------------------------------
    @staticmethod
    def build_record(cmd: int, data: bytes = b"", at: int = DATA_OFF,
                     sub: int | None = None, sub_at: int | None = None) -> bytes:
        p = bytearray(PAYLOAD)
        p[0] = cmd
        if sub is not None:
            p[1 if sub_at is None else sub_at] = sub & 0x07
        if data:
            p[at:at + len(data)] = bytes(data)
        return bytes(p)

    def send(self, payload: bytes) -> bool:
        return self.dev.send_feature(bytes([REPORT]) + bytes(payload))

    def answer(self, seconds: float = 1.0) -> bytes:
        return self.dev.read_input(seconds)

    def command(self, cmd: int, data: bytes = b"", at: int = DATA_OFF,
                sub: int | None = None, sub_at: int | None = None,
                wait: float = 1.0) -> tuple[bool, bytes]:
        ok = self.send(self.build_record(cmd, data, at=at, sub=sub, sub_at=sub_at))
        return ok, self.answer(wait)

    # -- profile ----------------------------------------------------------
    def write_profile(self, profile: bytes) -> tuple[bool, bytes]:
        if len(profile) != PROFILE_LEN:
            raise ValueError("profile must be 128 bytes")
        return self.command(0x04, profile)

    @staticmethod
    def profile_from_dump(dump: pathlib.Path, live: bool = True) -> bytes:
        data = dump.read_bytes()
        off = LIVE_PROFILE_OFF if live else FACTORY_PROFILE_OFF
        if len(data) < off + PROFILE_LEN:
            raise ValueError(f"{dump} is too small")
        return data[off:off + PROFILE_LEN]

    # -- lighting ---------------------------------------------------------
    def set_led(self, effect: int | None = None, mode: int | None = None,
                profile: bytes | None = None) -> bytes:
        """Write the lighting fields into the profile and push it.

        The MCU copies 0x0A (effect index) and 0x33 (effect mode) out of the
        profile and forwards them to the module.
        """
        prof = bytearray(profile if profile is not None else bytes(PROFILE_LEN))
        if effect is not None:
            prof[0x0A] = effect & 0xFF
        if mode is not None:
            prof[0x33] = mode & 0xFF
        prof[0x7E:0x80] = PROFILE_MARKER
        ok, frame = self.write_profile(bytes(prof))
        if not ok:
            raise RuntimeError("profile write failed")
        return bytes(prof)

    # -- clock ------------------------------------------------------------
    @staticmethod
    def clock_payload(now: dt.datetime | None = None,
                      head: bytes = b"\x00\x00\x00") -> bytes:
        """The vendor's clock payload: [date][cpu][x] + yy lo/hi mo dd hh mi ss wd."""
        now = now or dt.datetime.now()
        wd = (now.weekday() + 1) % 7        # 0 = Sunday, like the vendor app
        return bytes(head) + bytes([now.year % 100, now.year // 100, now.month,
                                   now.day, now.hour, now.minute, now.second, wd])

    def set_clock(self, record: int = 0x04, at: int = DATA_OFF, sub: int | None = None,
                  now: dt.datetime | None = None, head: bytes = b"\x00\x00\x00") -> tuple[bool, bytes]:
        payload = self.clock_payload(now, head)
        return self.command(record, payload, at=at, sub=sub,
                            sub_at=1 if record == 0x03 else (4 if record == 0x05 else None))

    def clock_sweep(self, now: dt.datetime | None = None) -> list[dict]:
        """Try every plausible (record, offset) with a distinct minute each.

        The screen shows the time, so the minute that is on screen tells which
        layout was accepted.
        """
        now = now or dt.datetime.now().replace(second=0, microsecond=0)
        plan = [
            (0x04, DATA_OFF, None), (0x04, 0, None), (0x04, 1, None),
            (0x05, DATA_OFF, 0), (0x05, DATA_OFF, 1), (0x05, DATA_OFF, 2),
            (0x03, DATA_OFF, 1), (0x03, DATA_OFF, 2), (0x03, DATA_OFF, 3),
            (0x03, DATA_OFF, 4),
        ]
        out = []
        for i, (rec, at, sub) in enumerate(plan):
            when = now + dt.timedelta(minutes=i)
            payload = self.clock_payload(when)
            ok, frame = self.command(rec, payload, at=at, sub=sub,
                                    sub_at=1 if rec == 0x03 else (4 if rec == 0x05 else None))
            out.append({"record": rec, "at": at, "sub": sub, "time": when,
                        "ok": ok, "frame": frame.hex(" ")})
            print(f"  rec 0x{rec:02X} @payload[{at}] sub={sub} -> {when:%H:%M} "
                  f"write={'ok' if ok else 'FAIL'} frame={frame.hex(' ') or '(none)'}")
            time.sleep(0.3)
        return out

    # -- screen (module cmd 0x81) -----------------------------------------
    def push_frame(self, pixels: bytes, timing: bool = True) -> int:
        """The vendor upload sequence.  The module renders a whole frame and
        needs the delays, so the timing is not optional."""
        blocks = (len(pixels) + SCREEN_BLOCK - 1) // SCREEN_BLOCK
        self.send(self.build_record(0x0D, bytes([0x01, 0x00]) +
                                    struct.pack("<HH", blocks, 50)))
        if timing:
            time.sleep(0.12)
        for seq in range(blocks):
            chunk = pixels[seq * SCREEN_BLOCK:(seq + 1) * SCREEN_BLOCK]
            chunk = chunk + bytes(SCREEN_BLOCK - len(chunk))
            self.send(self.build_record(0x0C, struct.pack("<HH", 0, seq) + chunk))
            if timing:
                time.sleep(0.05)
        if timing:
            time.sleep(0.05)
        self.send(self.build_record(0x0D, bytes([0x00, 0x00])))
        if timing:
            time.sleep(0.5)
        return blocks

    def close(self) -> None:
        self.dev.close()


# --------------------------------------------------------------------------
# image helpers
# --------------------------------------------------------------------------
def bmp_to_rgb565be(path: pathlib.Path, w: int = SCREEN_W, h: int = SCREEN_H) -> bytes:
    """Uncompressed 24/32 bit BMP -> RGB565 big endian pixels, top row first."""
    data = path.read_bytes()
    if data[:2] != b"BM":
        raise ValueError("not a BMP")
    off = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if compression != 0 or bpp not in (24, 32):
        raise ValueError("only uncompressed 24/32 bit BMP is supported")
    stride = ((width * bpp // 8) + 3) & ~3
    out = bytearray()
    for row in range(abs(height)):
        src_row = row if height > 0 else abs(height) - 1 - row
        base = off + src_row * stride
        for x in range(width):
            p = base + x * (bpp // 8)
            b, g, r = data[p], data[p + 1], data[p + 2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b & 0xF8)
            out += struct.pack(">H", v)
    if (width, abs(height)) != (w, h):
        raise ValueError(f"image is {width}x{abs(height)}, expected {w}x{h}")
    return bytes(out)


def solid_frame(w: int = SCREEN_W, h: int = SCREEN_H, rgb=(0, 0, 0)) -> bytes:
    v = ((rgb[0] & 0xF8) << 8) | ((rgb[1] & 0xFC) << 3) | (rgb[2] & 0xF8)
    return struct.pack(">H", v) * (w * h)
