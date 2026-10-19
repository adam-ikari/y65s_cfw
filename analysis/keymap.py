#!/usr/bin/env -S uv run python
"""keymap.py — decode the YD-Y65S (SH68F90A) factory key map.

The vendor firmware keeps its key map in flash as 4-byte records laid out
column-major, 6 slots per column (slot 0 of every column is unused because
the row line for bit 0 does not exist):

    record = [class, mod, hi, usage]

      class 0x00  keyboard: usage in the low byte, modifier mask in ``mod``
                  (a bare modifier key leaves ``usage`` at 0x00, a chord such
                  as Ctrl+Up carries both)
      class 0x02  consumer/system: 16-bit usage in ``hi:usage``
                  (0x00EA = Volume Decrement, 0x0192 = Browser, ...)
      class 0x07  layer action, sub-code in the low byte
      class 0x08  LED / backlight control, sub-codes in ``mod:hi:usage``
      class 0x0D  unassigned / disabled

Four layers are stored, each duplicated 0x400 bytes later (the duplicates are
byte-identical; the firmware keeps two copies inside every 2 KiB ISP page):

    layer 0  0xBC00  Mac base       (+ duplicate at 0xC000)
    layer 1  0xBE00  Windows base   (+ duplicate at 0xC200)
    layer 2  0xC400  Mac Fn         (+ duplicate at 0xC800)
    layer 3  0xC600  Windows Fn     (+ duplicate at 0xCA00)

Usage
-----
  uv run analysis/keymap.py dump  firmware/YD-Y65S_firmware.bin
  uv run analysis/keymap.py dump  firmware/YD-Y65S_firmware.bin --layer 3
  uv run analysis/keymap.py list  firmware/YD-Y65S_firmware.bin --layer 2
  uv run analysis/keymap.py check firmware/YD-Y65S_firmware.bin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# --- matrix geometry -------------------------------------------------------

MATRIX_COLS = 15
MATRIX_ROWS = 5  # key map slot 0 of every column is unused
SLOTS_PER_COL = MATRIX_ROWS + 1
RECORD_LEN = 4
LAYER_LEN = 0x200  # 90 records (0x168 bytes) padded up to 0x200

#: scan (and key map) order, leftmost column first.  These are the pins the
#: scanner drives low, one at a time (see the jump table at 0x35E8).
COL_PINS = [
    "P6.0", "P6.1", "P6.2", "P6.3", "P6.4", "P6.5", "P6.6", "P6.7",
    "P5.0", "P5.1", "P5.2", "P5.7", "P4.0", "P7.7", "P4.5",
]

#: top row first.  Read by 0xB130 into bits 1..5 of the column byte.
ROW_PINS = ["P7.1", "P7.2", "P7.3", "P5.3", "P5.4"]

LAYERS = [
    (0, "mac-base", 0xBC00, 0xC000),
    (1, "win-base", 0xBE00, 0xC200),
    (2, "mac-fn", 0xC400, 0xC800),
    (3, "win-fn", 0xC600, 0xCA00),
]

# --- HID naming ------------------------------------------------------------

_USAGE_NAMES = {
    0x28: "Enter", 0x29: "Esc", 0x2A: "BkSp", 0x2B: "Tab", 0x2C: "Space",
    0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\", 0x32: "#",
    0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",", 0x37: ".", 0x38: "/",
    0x39: "Caps", 0x46: "PrtSc", 0x47: "ScrLk", 0x48: "Pause", 0x49: "Ins",
    0x4A: "Home", 0x4B: "PgUp", 0x4C: "Del", 0x4D: "End", 0x4E: "PgDn",
    0x4F: "Right", 0x50: "Left", 0x51: "Down", 0x52: "Up",
    0x53: "NumLk", 0x54: "KP/", 0x55: "KP*", 0x56: "KP-", 0x57: "KP+",
    0x58: "KPEnter", 0x63: "KP,",
    0x67: "KP=", 0x68: "KP1", 0x69: "KP2", 0x6A: "KP3", 0x6B: "KP4",
    0x6C: "KP5", 0x6D: "KP6", 0x6E: "KP7", 0x6F: "KP8", 0x70: "KP9",
    0x71: "KP0", 0x7F: "Mute", 0x80: "VolUp", 0x81: "VolDn", 0x84: "Power",
}

#: consumer page (0x0C) usages, the ones the vendor key map actually uses
_CONSUMER_NAMES = {
    0x0021: "AC Search", 0x006F: "BrightUp", 0x0070: "BrightDn", 0x00B5: "NextTrack",
    0x00B6: "PrevTrack", 0x00B7: "StopTrack", 0x00CD: "PlayPause", 0x00E2: "Mute",
    0x00E9: "VolUp", 0x00EA: "VolDn", 0x0183: "KbdBL", 0x0192: "Browser",
    0x0194: "Calculator", 0x0196: "Explorer", 0x0221: "WWW", 0x0223: "AC Home",
    0x0224: "AC Back", 0x0225: "AC Forward", 0x00CF: "MediaSel",
}

_MOD_NAMES = [
    (0x01, "LCtrl"), (0x02, "LShift"), (0x04, "LAlt"), (0x08, "LGui"),
    (0x10, "RCtrl"), (0x20, "RShift"), (0x40, "RAlt"), (0x80, "RGui"),
]

_CLASS_NAMES = {0x00: "key", 0x02: "consumer", 0x07: "layer", 0x08: "led", 0x0D: "off"}


def usage_name(u: int) -> str:
    if 0x04 <= u <= 0x1D:
        return "abcdefghijklmnopqrstuvwxyz"[u - 0x04]
    if 0x1E <= u <= 0x26:
        return str(u - 0x1D)
    if u == 0x27:
        return "0"
    if 0x3A <= u <= 0x45:
        return f"F{u - 0x39}"
    return _USAGE_NAMES.get(u, f"0x{u:02X}")


def mods_name(mask: int) -> str:
    if mask == 0:
        return ""
    return "+".join(name for bit, name in _MOD_NAMES if mask & bit) or f"0x{mask:02X}"


def decode(rec: bytes) -> str:
    cls, b1, b2, b3 = rec
    if cls == b1 == b2 == b3 == 0:
        return "-"
    if cls == 0x00:
        mods, u = mods_name(b1), b3
        if u == 0:
            return mods or "-"
        return f"{mods}+{usage_name(u)}" if mods else usage_name(u)
    if cls == 0x02:
        return _CONSUMER_NAMES.get((b2 << 8) | b3, f"consumer 0x{b2:02X}{b3:02X}")
    if cls == 0x07:
        return f"layer-fn(0x{b3:02X})"
    if cls == 0x08:
        return f"led({b1:02X}:{b2:02X}:{b3:02X})"
    return f"{_CLASS_NAMES.get(cls, 'class')} 0x{cls:02X}:{b1:02X}:{b2:02X}:{b3:02X}"


def record(data: bytes, layer_addr: int, col: int, row: int) -> bytes:
    off = layer_addr + RECORD_LEN * (col * SLOTS_PER_COL + row)
    return data[off:off + RECORD_LEN]


def layer_name(index: int) -> str:
    for i, name, _, _ in LAYERS:
        if i == index:
            return name
    raise SystemExit(f"unknown layer {index} (0..{len(LAYERS) - 1})")


# --- commands --------------------------------------------------------------

def cmd_dump(args) -> None:
    data = Path(args.file).read_bytes()
    idx = args.layer
    _, name, addr, dup = LAYERS[idx]
    print(f"layer {idx} ({name})  flash 0x{addr:04X}  (duplicate 0x{dup:04X})")
    print(f"      {'slot0':>6}   {'row0':>6}   {'row1':>6}   {'row2':>6}   "
          f"{'row3':>6}   {'row4':>6}    <- row slot (physical row 0..4)")
    for c in range(MATRIX_COLS):
        cells = []
        for r in range(SLOTS_PER_COL):
            off = addr + RECORD_LEN * (c * SLOTS_PER_COL + r)
            cells.append(f"{decode(data[off:off + RECORD_LEN]):>6}")
        print(f"  col{c:2d} ({COL_PINS[c]:>5})  " + "  ".join(cells))
    print("\nrow pins, top row first: " + ", ".join(ROW_PINS))


def cmd_list(args) -> None:
    data = Path(args.file).read_bytes()
    idx = args.layer
    _, name, addr, _ = LAYERS[idx]
    n = 0
    for c in range(MATRIX_COLS):
        for r in range(SLOTS_PER_COL):
            off = addr + RECORD_LEN * (c * SLOTS_PER_COL + r)
            rec = data[off:off + RECORD_LEN]
            if not any(rec):
                continue
            print(f"  col{c:2d} row{r}  ({COL_PINS[c]:>5} x {ROW_PINS[r - 1] if r else '-'})"
                  f"  0x{addr + RECORD_LEN * (c * SLOTS_PER_COL + r):04X}  "
                  f"{rec.hex(' ').upper()}  {decode(rec)}")
            n += 1
    print(f"{n} assigned keys on layer {idx} ({name})")


def cmd_check(args) -> None:
    data = Path(args.file).read_bytes()
    ok = True
    print("duplicate copies (each layer is stored twice, 0x400 apart):")
    for idx, name, addr, dup in LAYERS:
        same = data[addr:addr + LAYER_LEN] == data[dup:dup + LAYER_LEN]
        ok &= same
        print(f"  {name:<9} 0x{addr:04X} == 0x{dup:04X} : {'yes' if same else 'NO'}")
    print("\nlayer differences (cells that differ):")
    for idx, name, addr, _ in LAYERS:
        for idx2, name2, addr2, _ in LAYERS:
            if idx2 <= idx:
                continue
            diff = []
            for c in range(MATRIX_COLS):
                for r in range(SLOTS_PER_COL):
                    a = data[addr + RECORD_LEN * (c * SLOTS_PER_COL + r):
                             addr + RECORD_LEN * (c * SLOTS_PER_COL + r) + RECORD_LEN]
                    b = data[addr2 + RECORD_LEN * (c * SLOTS_PER_COL + r):
                             addr2 + RECORD_LEN * (c * SLOTS_PER_COL + r) + RECORD_LEN]
                    if a != b:
                        diff.append((c, r, a, b))
            print(f"  {name} vs {name2}: {len(diff)} cell(s)")
            for c, r, a, b in diff:
                print(f"      col{c:2d} row{r}: {name}={decode(a)}  {name2}={decode(b)}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="keymap", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("file", help="firmware dump, e.g. firmware/YD-Y65S_firmware.bin")

    p = sub.add_parser("dump", help="print one layer as a column x row grid")
    common(p)
    p.add_argument("--layer", type=int, default=0, choices=[l[0] for l in LAYERS])

    p = sub.add_parser("list", help="print the assigned keys of one layer")
    common(p)
    p.add_argument("--layer", type=int, default=0, choices=[l[0] for l in LAYERS])

    p = sub.add_parser("check", help="verify duplicate copies and layer diffs")
    common(p)

    args = ap.parse_args()
    return {"dump": cmd_dump, "list": cmd_list, "check": cmd_check}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
