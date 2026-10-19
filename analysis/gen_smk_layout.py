#!/usr/bin/env -S uv run python
"""gen_smk_layout.py — emit an SMK ``layout.c`` from the YD-Y65S factory key map.

The vendor key map is the ground truth (see ``keymap.py``).  This tool turns the
four 4-byte-record layers into SMK's ``uint16_t keymaps[][MATRIX_ROWS][MATRIX_COLS]``
so the port can never drift from the dump by a hand-copied transcription.

Layer order in the emitted file is chosen so that SMK's default layer (0) is the
Windows base layer, which is what the board uses out of the box:

    SMK layer 0  _WIN_BL    vendor 0xBE00
    SMK layer 1  _MAC_BL    vendor 0xBC00
    SMK layer 2  _WIN_FL    vendor 0xC600
    SMK layer 3  _MAC_FL    vendor 0xC400

Usage
-----
  uv run analysis/gen_smk_layout.py firmware/YD-Y65S_firmware.bin \
      > src/keyboards/yd-y65s/layouts/default/layout.c

Anything the vendor does that SMK has no primitive for (multi-modifier chords,
the class-0x08 LED actions) becomes ``KC_NO`` with a ``/* ... */`` comment naming
the raw record, so the gaps stay greppable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import keymap as km

# SMK layer index / name / vendor flash address, in emitted order.
LAYER_SOURCES = [
    (0, "_WIN_BL", 0xBE00, "win-base"),
    (1, "_MAC_BL", 0xBC00, "mac-base"),
    (2, "_WIN_FL", 0xC600, "win-fn"),
    (3, "_MAC_FL", 0xC400, "mac-fn"),
]

MOD_KEY = {
    0x01: "KC_LCTL", 0x02: "KC_LSFT", 0x04: "KC_LALT", 0x08: "KC_LGUI",
    0x10: "KC_RCTL", 0x20: "KC_RSFT", 0x40: "KC_RALT", 0x80: "KC_RGUI",
}
MOD_MACRO = {
    0x01: "LCTL", 0x02: "LSFT", 0x04: "LALT", 0x08: "LGUI",
    0x10: "RCTL", 0x20: "RSFT", 0x40: "RALT", 0x80: "RGUI",
}

KEY_KC = {
    0x28: "KC_ENT", 0x29: "KC_ESC", 0x2A: "KC_BSPC", 0x2B: "KC_TAB", 0x2C: "KC_SPC",
    0x2D: "KC_MINS", 0x2E: "KC_EQL", 0x2F: "KC_LBRC", 0x30: "KC_RBRC", 0x31: "KC_BSLS",
    0x32: "KC_NUHS", 0x33: "KC_SCLN", 0x34: "KC_QUOT", 0x35: "KC_GRV", 0x36: "KC_COMM",
    0x37: "KC_DOT", 0x38: "KC_SLSH", 0x39: "KC_CAPS",
    0x46: "KC_PSCR", 0x47: "KC_SCRL", 0x48: "KC_PAUS", 0x49: "KC_INS", 0x4A: "KC_HOME",
    0x4B: "KC_PGUP", 0x4C: "KC_DEL", 0x4D: "KC_END", 0x4E: "KC_PGDN", 0x4F: "KC_RGHT",
    0x50: "KC_LEFT", 0x51: "KC_DOWN", 0x52: "KC_UP",
    0x65: "KC_APP", 0x66: "KC_PWR",
    0x68: "KC_F13", 0x69: "KC_F14", 0x6A: "KC_F15", 0x6B: "KC_F16",
    0x6C: "KC_F17", 0x6D: "KC_F18", 0x6E: "KC_F19", 0x6F: "KC_F20",
    0x70: "KC_F21", 0x71: "KC_F22", 0x72: "KC_F23", 0x73: "KC_F24",
}

CONSUMER_KC = {
    0x0021: "KC_WSCH",    # AC Search
    0x006F: "KC_BRIU",    # Brightness Up
    0x0070: "KC_BRID",    # Brightness Down
    0x00B5: "KC_MNXT",
    0x00B6: "KC_MPRV",
    0x00B7: "KC_MSTP",
    0x00CD: "KC_MPLY",
    0x00E2: "KC_MUTE",
    0x00E9: "KC_VOLU",
    0x00EA: "KC_VOLD",
    0x0183: "BL_TOGG",    # Keyboard Backlight
    0x0192: "KC_WHOM",    # Browser (vendor "Browser")
    0x0194: "KC_CALC",
    0x0196: "KC_MYCM",    # Explorer
    0x0221: "KC_WHOM",    # WWW
    0x0223: "KC_WHOM",    # AC Home
    0x0224: "KC_WBAK",    # AC Back
    0x0225: "KC_WFWD",    # AC Forward
    0x00CF: "KC_MSEL",    # Media Select
}


def keyboard_kc(usage: int) -> str | None:
    if 0x04 <= usage <= 0x1D:
        return "KC_" + chr(ord("A") + usage - 0x04)
    if 0x1E <= usage <= 0x26:
        return "KC_" + str(usage - 0x1D)
    if usage == 0x27:
        return "KC_0"
    if 0x3A <= usage <= 0x45:
        return "KC_F" + str(usage - 0x39)
    return KEY_KC.get(usage)


def record_to_kc(rec: bytes, layer_index: int) -> str:
    cls, b1, b2, b3 = rec
    if cls == b1 == b2 == b3 == 0:
        return "KC_NO"

    if cls == 0x00:
        mods, usage = b1, b3
        if usage == 0:
            if mods in MOD_KEY:
                return MOD_KEY[mods]
            return f"KC_NO /* mods 0x{mods:02X} */"
        kc = keyboard_kc(usage)
        if kc is None:
            return f"KC_NO /* usage 0x{usage:02X} */"
        if mods == 0:
            return kc
        if mods in MOD_MACRO:
            return f"{MOD_MACRO[mods]}({kc})"
        return f"KC_NO /* chord mods 0x{mods:02X}+{kc} */"

    if cls == 0x02:
        usage = (b2 << 8) | b3
        return CONSUMER_KC.get(usage, f"KC_NO /* consumer 0x{usage:04X} */")

    if cls == 0x07:
        if b1 == 0 and b3 == 0x0D:
            return "FN_MAC" if layer_index in (1, 3) else "FN_WIN"
        return f"KC_NO /* vendor layer action 07:{b1:02X}:{b2:02X}:{b3:02X} */"

    if cls == 0x08:
        return f"KC_NO /* vendor LED {b1:02X}:{b2:02X}:{b3:02X} */"

    if cls == 0x0D:
        return "KC_NO"

    return f"KC_NO /* class 0x{cls:02X} {b1:02X}:{b2:02X}:{b3:02X} */"


def emit_macro(out: list[str]) -> None:
    out.append("#define LAYOUT_65( \\")
    for r in range(km.MATRIX_ROWS):
        args = ", ".join(f"K{c:02d}_{r}" for c in range(km.MATRIX_COLS))
        sep = ", \\" if r != km.MATRIX_ROWS - 1 else " \\"
        out.append(f"    {args}{sep}")
    out.append(") { \\")
    for r in range(km.MATRIX_ROWS):
        row = ", ".join(f"K{c:02d}_{r}" for c in range(km.MATRIX_COLS))
        sep = ", \\" if r != km.MATRIX_ROWS - 1 else " \\"
        out.append(f"    {{ {row} }}{sep}")
    out.append("}")
    out.append("")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    data = Path(sys.argv[1]).read_bytes()
    out: list[str] = []

    out.append("// Generated by analysis/gen_smk_layout.py from the factory dump.")
    out.append("// Do not edit by hand; re-run the generator instead:")
    out.append("//   uv run analysis/gen_smk_layout.py firmware/YD-Y65S_firmware.bin")
    out.append("//       > src/keyboards/yd-y65s/layouts/default/layout.c")
    out.append("//")
    out.append("// Layer order puts the Windows base layer first so SMK's default")
    out.append("// (layer 0) matches the board's out-of-the-box behaviour.")
    out.append("")
    out.append('#include "kbdef.h"')
    out.append('#include "layout.h"')
    out.append('#include "user_layout.h"')
    out.append('#include "report.h"')
    out.append("#include <stdint.h>")
    out.append("")
    out.append("// clang-format off")
    out.append("")
    emit_macro(out)

    out.append("#define _WIN_BL 0")
    out.append("#define _MAC_BL 1")
    out.append("#define _WIN_FL 2")
    out.append("#define _MAC_FL 3")
    out.append("")
    out.append("#define FN_WIN MO(_WIN_FL)")
    out.append("#define FN_MAC MO(_MAC_FL)")
    out.append("")
    out.append("const uint16_t keymaps[][MATRIX_ROWS][MATRIX_COLS] = {")

    for index, name, addr, label in LAYER_SOURCES:
        out.append(f"    /* {label}, vendor 0x{addr:04X} */")
        out.append(f"    [{name}] = LAYOUT_65(")
        for r in range(km.MATRIX_ROWS):
            cells = []
            for c in range(km.MATRIX_COLS):
                off = addr + km.RECORD_LEN * (c * km.SLOTS_PER_COL + (r + 1))
                cells.append(record_to_kc(data[off:off + km.RECORD_LEN], index))
            sep = "," if r != km.MATRIX_ROWS - 1 else ""
            out.append("        " + ", ".join(cells) + sep)
        out.append("    ),")
    out.append("};")
    out.append("")
    out.append("// clang-format on")
    out.append("")
    out.append("uint8_t layout_os_base_layer(bool is_mac)")
    out.append("{")
    out.append("    return is_mac ? _MAC_BL : _WIN_BL;")
    out.append("}")
    out.append("")

    sys.stdout.write("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
