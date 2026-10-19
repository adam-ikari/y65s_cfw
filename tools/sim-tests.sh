#!/usr/bin/env bash
# sim-tests.sh — run the YD-Y65S firmware in SMK's patched uCsim.
#
# Two groups:
#   1. tests/            YD-Y65S matrix -> scan -> keymap -> HID report, with
#                        every expectation read from the factory dump
#                        (board-specific; replaces SMK's Air60 key tests).
#   2. tools/smk/tests   SMK's board-agnostic boot / USB / ISP / stack tests,
#                        pointed at this firmware.
#
# SMK's own TestKeyEvent and TestWorstCaseStack emulate the Air60 matrix wiring,
# so they are excluded here and covered for this board by tests/test_y65s_sim.py.
#
# Usage:  SMK_UCSIM=... SMK_FIRMWARE=... bash tools/sim-tests.sh
# Defaults: SMK_UCSIM=~/ucsim-build/sdcc-4.5.0/sim/ucsim/src/sims/s51.src/ucsim_51
#           SMK_FIRMWARE=<repo>/build/smk-yd-y65s/yd-y65s_default_smk.hex

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"

export SMK_UCSIM="${SMK_UCSIM:-$HOME/ucsim-build/sdcc-${SDCC_VER:-4.5.0}/sim/ucsim/src/sims/s51.src/ucsim_51}"
export SMK_FIRMWARE="${SMK_FIRMWARE:-$repo/build/smk-yd-y65s/yd-y65s_default_smk.hex}"

[ -x "$SMK_UCSIM" ] || { echo "simulator not found/executable: $SMK_UCSIM" >&2
                         echo "(run tools/build-ucsim.ps1)" >&2; exit 1; }
[ -f "$SMK_FIRMWARE" ] || { echo "firmware not found: $SMK_FIRMWARE" >&2
                            echo "(run tools/build-port.ps1)" >&2; exit 1; }
[ -d "$repo/tools/smk/tests" ] || { echo "SMK checkout missing; run tools/fetch-tools.ps1" >&2; exit 1; }

echo "simulator: $SMK_UCSIM"
echo "firmware:  $SMK_FIRMWARE"

echo
echo "== YD-Y65S board tests =="
(cd "$repo" && python3 -m unittest discover -s tests -t tests -v)

echo
echo "== SMK board-agnostic tests =="
(cd "$repo/tools/smk/tests" && python3 -m unittest -v \
    test_boot \
    test_source_breakpoints \
    test_stack.TestStackOverflow \
    test_usb.TestEnumerationThroughInit \
    test_usb.TestGetDescriptor \
    test_usb.TestHidRequests \
    test_usb.TestIspJump \
    test_usb.TestKeyboardReport \
    test_usb.TestStandardRequests \
    test_usb.TestUsbInterrupt)
