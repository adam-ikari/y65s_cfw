#!/usr/bin/env python3
"""End-to-end simulation tests for the YD-Y65S SMK port.

These run the *built* firmware (``build/smk-yd-y65s/yd-y65s_default_smk.hex``)
inside SMK's patched uCsim — the SH68F90 model whose USB interrupt is a real,
registered source — and drive the YD-Y65S key matrix from the test side.

The MCU model knows nothing about what is soldered to the pins, so the matrix is
emulated here (SMK's harness calls this "devices").  The Air60 model in
``tools/smk/tests/devices.py`` already has the same row lines as this board; the
only difference is the column wiring, so we reuse the session/boot/report
plumbing and swap in the YD-Y65S columns.

Because the expectation for every key is read straight out of the factory dump
(``firmware/YD-Y65S_firmware.bin``), this is a real cross-check of the port:
wiring -> scan -> keymap -> HID report.

Environment:
  SMK_UCSIM     path to the patched ``ucsim-sh68f90`` binary
  SMK_FIRMWARE  path to ``yd-y65s_default_smk.hex``

Run from the repository root inside WSL (the simulator is a Linux binary)::

    SMK_UCSIM=... SMK_FIRMWARE=... python3 -m unittest discover -s tests -t tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SMK_TESTS = REPO / "tools" / "smk" / "tests"
ANALYSIS = REPO / "analysis"

for _p in (SMK_TESTS, ANALYSIS):
    if not _p.is_dir():
        raise SystemExit(
            f"{_p} not found; run tools/fetch-tools.ps1 (SMK) first"
        )
    sys.path.insert(0, str(_p))

import keymap  # noqa: E402  (analysis/keymap.py, stdlib only)
from devices import Air60Sim, KeyMatrix  # noqa: E402  (tools/smk/tests/devices.py)

# --- YD-Y65S wiring (src/keyboards/yd-y65s/kbdef.h) -------------------------

# P-register SFR addresses (src/sino51lib/sh68f90/sh68f90.h).
P4, P5, P6, P7 = 0xB0, 0x88, 0xC0, 0xF8

# Columns, in scanner (and key-map) order.  Same pin list as
# analysis/keymap.py:COL_PINS, and the same order gen_smk_layout.py emits.
COL_PIN = {
    0: (P6, 0), 1: (P6, 1), 2: (P6, 2), 3: (P6, 3), 4: (P6, 4), 5: (P6, 5),
    6: (P6, 6), 7: (P6, 7),
    8: (P5, 0), 9: (P5, 1), 10: (P5, 2), 11: (P5, 7),
    12: (P4, 0), 13: (P7, 7), 14: (P4, 5),
}

# The firmware's default layer (SMK layer 0) is the Windows base layer, which
# the generator takes from the vendor's win-base table.
WIN_BASE_ADDR = 0xBE00
FIRMWARE_BIN = REPO / "firmware" / "YD-Y65S_firmware.bin"

# (col, row) -> human name, chosen so every expected code is a plain key (no
# modifier, no chord) and the four positions exercise four different ports.
PROBES = [
    (0, 0, "Esc"),
    (2, 1, "W"),
    (1, 2, "A"),
    (3, 2, "D"),
]


def expected_usage(col: int, row: int) -> int:
    """HID keyboard usage the factory win-base layer assigns to (col, row).

    ``keymap.record`` indexes slots, not rows: slot 0 of every column is unused
    because the matrix has no row line for bit 0.
    """
    data = FIRMWARE_BIN.read_bytes()
    cls, mod, _hi, usage = keymap.record(data, WIN_BASE_ADDR, col, row + 1)
    if cls != 0x00 or mod != 0 or usage == 0:
        raise AssertionError(
            f"({col},{row}) is not a plain key in the dump "
            f"(class=0x{cls:02X} mod=0x{mod:02X} usage=0x{usage:02X})"
        )
    return usage


# --- test-side board model --------------------------------------------------


class Y65sKeyMatrix(KeyMatrix):
    """KeyMatrix with this board's column pins (rows are identical to the Air60)."""

    def _col_driven_low(self, sess, col, port_cache):
        sfr, bit = COL_PIN[col]
        v = port_cache.get(sfr)
        if v is None:
            v = port_cache[sfr] = sess.get_sfr(sfr) or 0
        return (v & (1 << bit)) == 0


class Y65sSim(Air60Sim):
    """Air60 session logic pointed at the YD-Y65S matrix.

    The boot/scan/report plumbing is board-agnostic; only the matrix differs.
    """

    def __init__(self, firmware=None, sim=None):
        super().__init__(firmware, sim)
        self.matrix = Y65sKeyMatrix()


# --- tests ------------------------------------------------------------------


class TestY65sMatrix(unittest.TestCase):
    """A physical key press must propagate through the real scan path."""

    @classmethod
    def setUpClass(cls):
        cls.kb = Y65sSim()
        cls.kb.boot(usb=True)
        cls.kb.mark_usb_configured()

    @classmethod
    def tearDownClass(cls):
        cls.kb.close()

    def _press_and_read(self, col, row):
        self.kb.matrix.clear()
        self.kb.matrix.press(col, row)
        reps = self.kb.scan_for_report()
        # Release and let the scan settle so the next probe starts clean.
        self.kb.matrix.clear()
        self.kb.scan_for_report(max_hits=80)
        return reps

    def test_probes_resolve_to_the_dumped_keymap(self):
        for col, row, name in PROBES:
            with self.subTest(key=name, col=col, row=row):
                usage = expected_usage(col, row)
                reps = self._press_and_read(col, row)
                self.assertTrue(
                    reps, f"{name} at ({col},{row}) produced no EP1 report"
                )
                self.assertEqual(
                    reps[-1],
                    [0x00, 0x00, usage, 0x00, 0x00, 0x00, 0x00, 0x00],
                    f"{name} at ({col},{row}) should report HID 0x{usage:02X}; "
                    f"got {reps[-1]}",
                )

    def test_idle_matrix_reports_nothing(self):
        self.kb.matrix.clear()
        reps = self.kb.scan_for_report(max_hits=80)
        self.assertEqual(reps, [], f"idle matrix must not report; got {reps}")


if __name__ == "__main__":
    unittest.main()
