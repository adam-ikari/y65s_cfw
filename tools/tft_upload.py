"""Upload a static image to the TFT module's user-animation area.

Replicates the ODM vendor tool `zu` (SET_TFT_USER_ANIMATION):
  payload = 256-byte delay header + RGB565 (little-endian) pixels
  chunked into 504-byte pieces, each prefixed with
      AA 50 <idx_lo> <idx_hi> <cnt_lo> <cnt_hi> 50 06
  and delivered through feature report 9 with record cmd 0x05,
  payload[4] = 0x00 -> module command 0x6E, 512 bytes from payload[7].

Writes the module's user-animation area (flash offset 0x650000),
NOT the keyboard firmware.  Requires explicit user consent.
"""

from __future__ import annotations

import argparse
import ctypes
import pathlib
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

REPORT = 9
RECORD = 0x05
SUB_CMD = 0x00          # payload[4]: 0 -> module cmd 0x6E (SET_TFT_USER_ANIMATION)
PAYLOAD_LEN = 519
DATA_OFF = 7            # data starts at payload[7]
CHUNK_TOTAL = 512       # bytes the firmware streams per record
CHUNK_DATA = CHUNK_TOTAL - 8


def rgb565(r: int, g: int, b: int) -> bytes:
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | ((b & 0xF8) >> 3)
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


def test_pattern(w: int, h: int) -> bytes:
    """Four quadrants + crosshair + white border: reveals rotation/flip."""
    out = bytearray()
    border = max(2, min(w, h) // 40)
    for y in range(h):
        for x in range(w):
            if x < border or y < border or x >= w - border or y >= h - border:
                px = (255, 255, 255)
            elif abs(x - w // 2) <= 1 or abs(y - h // 2) <= 1:
                px = (0, 0, 0)
            elif x < w // 2 and y < h // 2:
                px = (255, 0, 0)        # top-left red
            elif x >= w // 2 and y < h // 2:
                px = (0, 255, 0)        # top-right green
            elif x < w // 2 and y >= h // 2:
                px = (0, 0, 255)        # bottom-left blue
            else:
                px = (255, 255, 0)      # bottom-right yellow
            out += rgb565(*px)
    return bytes(out)


def build_stream(pixels: bytes, frames: int = 1) -> bytes:
    header = bytearray([0xFF] * 256)
    header[0] = frames
    for i in range(frames - 1):
        header[i + 1] = 0          # delay * 5
    header[frames] = 0
    return bytes(header) + pixels


def open_dev():
    args = types.SimpleNamespace(vid=0x258A, pid=0x019D, page=0xFF02, usage=2)
    e = vh.pick(vh.enumerate_hid(), args)
    vh.guard(e, REPORT)
    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=135)
    ap.add_argument("--h", type=int, default=240)
    ap.add_argument("--delay", type=float, default=1.8,
                    help="seconds between chunks (firmware drops records while busy)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--file", default=None, help="optional BMP to use instead of test pattern")
    a = ap.parse_args()

    pixels = test_pattern(a.w, a.h)
    stream = build_stream(pixels, 1)
    total = len(stream)
    nchunks = (total + CHUNK_DATA - 1) // CHUNK_DATA
    print(f"image {a.w}x{a.h}  pixels {len(pixels)} B  stream {total} B  "
          f"chunks {nchunks} x {CHUNK_DATA} B  delay {a.delay}s  "
          f"eta {(nchunks - a.start) * a.delay / 60:.1f} min")
    if a.dry_run:
        return 0

    e = open_dev()
    handle = e["handle"]
    length = max(e["caps"].FeatureReportByteLength, REPORT + 1)
    t0 = time.time()
    for idx in range(a.start, nchunks):
        piece = stream[idx * CHUNK_DATA:(idx + 1) * CHUNK_DATA]
        piece = piece + b"\x00" * (CHUNK_DATA - len(piece))
        packet = bytes((0xAA, 0x50,
                        idx & 0xFF, (idx >> 8) & 0xFF,
                        nchunks & 0xFF, (nchunks >> 8) & 0xFF,
                        0x50, 0x06)) + piece
        assert len(packet) == CHUNK_TOTAL

        payload = bytearray(PAYLOAD_LEN)
        payload[0] = RECORD
        payload[4] = SUB_CMD
        payload[DATA_OFF:DATA_OFF + CHUNK_TOTAL] = packet

        buf = ctypes.create_string_buffer(length)
        buf[0] = bytes([REPORT])
        buf[1:1 + PAYLOAD_LEN] = bytes(payload)
        ok = vh.hid.HidD_SetFeature(handle, buf, length)
        if not ok:
            print(f"chunk {idx}: FAILED err={ctypes.get_last_error()}", flush=True)
            return 1
        if idx % 10 == 0 or idx == nchunks - 1:
            el = time.time() - t0
            done = idx - a.start + 1
            eta = (nchunks - idx - 1) * (el / done)
            print(f"chunk {idx + 1}/{nchunks}  {el:.0f}s elapsed  eta {eta:.0f}s",
                  flush=True)
        if idx != nchunks - 1:
            time.sleep(a.delay)
    print("upload done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
