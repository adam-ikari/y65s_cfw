#!/usr/bin/env python3
"""Print a region of an fwdis.py linear disassembly (`--out` listing).

Usage:
    uv run analysis/lst.py build/fw_full.lst 0x0560 0x0760
    uv run analysis/lst.py build/fw_full.lst 0x9BF9 0x9C40 -c 40
"""
from __future__ import annotations

import argparse
import re
import sys

# "  0561: 90 0E E4    MOV DPTR,#0x0EE4"  (labels/"call-site" lines have no "NNNN:" prefix)
LINE = re.compile(r"^\s*([0-9A-Fa-f]{1,4}):\s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lst", help="listing produced by: fwdis.py dis <bin> --out <lst>")
    ap.add_argument("start", help="first address, e.g. 0x0560")
    ap.add_argument("end", help="last address, e.g. 0x0760")
    ap.add_argument("-c", "--count", type=int, default=0, help="stop after N instruction lines (0 = no limit)")
    ap.add_argument("--no-labels", action="store_true", help="drop non-instruction lines (labels / comments)")
    args = ap.parse_args()

    lo = int(args.start, 16)
    hi = int(args.end, 16)
    shown = 0
    with open(args.lst, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = LINE.match(line)
            if m:
                addr = int(m.group(1), 16)
                if addr < lo or addr > hi:
                    continue
                shown += 1
            elif args.no_labels or line.strip() == "":
                continue
            else:
                # keep label lines only when they sit inside the requested window
                continue
            sys.stdout.write(line)
            if args.count and shown >= args.count:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
