#!/usr/bin/env -S uv run python
"""fwdis.py — analysis CLI for the YD-Y65S 8051 firmware image.

Usage examples
--------------
  uv run analysis/fwdis.py info   firmware/YD-Y65S_full.bin
  uv run analysis/fwdis.py dis     firmware/YD-Y65S_firmware.bin --start 0x89D7 --len 0x60
  uv run analysis/fwdis.py dis     firmware/YD-Y65S_firmware.bin --reachable --out build/fw.lst
  uv run analysis/fwdis.py xref    firmware/YD-Y65S_firmware.bin
  uv run analysis/fwdis.py sfr     firmware/YD-Y65S_firmware.bin
  uv run analysis/fwdis.py xdata   firmware/YD-Y65S_firmware.bin
  uv run analysis/fwdis.py strings firmware/YD-Y65S_firmware.bin
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcs51 import (  # noqa: E402
    Instr,
    SFR_NAMES,
    bit_name,
    dir_name,
    disasm_one,
    linear_sweep,
    recursive_traverse,
    xsfr_name,
)

# 8051 interrupt vector table slot addresses (entry = 8 bytes apart)
VECTORS = [
    (0x0000, "reset"),
    (0x0003, "ext_int0"),
    (0x000B, "timer0"),
    (0x0013, "ext_int1"),
    (0x001B, "timer1"),
    (0x0023, "uart"),
    (0x002B, "timer2"),
    (0x0033, "vec_33"),
    (0x003B, "vec_3B"),
    (0x0043, "vec_43"),
    (0x004B, "vec_4B"),
    (0x0053, "vec_53"),
    (0x005B, "vec_5B"),
    (0x0063, "vec_63"),
    (0x006B, "vec_6B"),
]


def load(path: str) -> bytes:
    return Path(path).read_bytes()


def cmd_info(args) -> None:
    data = load(args.file)
    base = args.base
    print(f"file   : {args.file}")
    print(f"size   : {len(data)} bytes (0x{len(data):X})  base 0x{base:04X}")

    hist = Counter(data)
    top = hist.most_common(8)
    print("top    : " + " ".join(f"{v:02X}x{c}({c/len(data)*100:.1f}%)" for v, c in top))

    print(f"\nentropy per {args.block}B block:")
    line = []
    for off in range(0, len(data), args.block):
        blk = data[off:off + args.block]
        h = Counter(blk)
        e = -sum((c / len(blk)) * math.log2(c / len(blk)) for c in h.values())
        line.append(f"{base+off:04X} {e:4.2f}")
        if len(line) == 8:
            print("  " + "  ".join(line))
            line = []
    if line:
        print("  " + "  ".join(line))

    print("\ninterrupt vectors:")
    for addr, name in VECTORS:
        off = addr - base
        if not (0 <= off < len(data) - 2):
            continue
        ins = disasm_one(data[off - off + off:], off) if False else None
        # decode at the vector slot using image-relative indexing
        img = data
        op = img[off]
        if op == 0x02:
            t = (img[off + 1] << 8) | img[off + 2]
            print(f"  {addr:04X} {name:<10} LJMP 0x{t:04X}")
        elif op == 0x00:
            print(f"  {addr:04X} {name:<10} (unused)")
        else:
            b = img[off:off + 4]
            print(f"  {addr:04X} {name:<10} inline: {b.hex(' ').upper()}")

    print("\nruns of >=64 identical bytes:")
    i = 0
    found = False
    while i < len(data):
        j = i
        while j + 1 < len(data) and data[j + 1] == data[i]:
            j += 1
        if j - i + 1 >= 64:
            found = True
            print(f"  {base+i:04X}..{base+j:04X}  {j-i+1:6d} bytes of 0x{data[i]:02X}")
        i = j + 1
    if not found:
        print("  (none)")


def render(ins: Instr, labels: dict[int, str] | None = None) -> str:
    text = ins.mnemonic
    if labels and ins.target is not None and ins.target in labels:
        text = text.split(" 0x")[0] + f" {labels[ins.target]}"
    return text


def cmd_dis(args) -> None:
    data = load(args.file)
    base = args.base

    if args.reachable:
        seeds = [base]
        for addr, _ in VECTORS[1:]:
            off = addr - base
            if 0 <= off < len(data) - 2 and data[off] == 0x02:
                seeds.append((data[off + 1] << 8) | data[off + 2])
        reached = recursive_traverse(data, [s - base for s in seeds])
        addrs = sorted(reached)
        print(f"; recursive traversal from {len(seeds)} seeds: "
              f"{len(addrs)} instructions, "
              f"{sum(i.length for i in reached.values())} bytes covered", file=sys.stderr)
    else:
        start = args.start - base
        length = args.len
        end = start + length if length is not None else (args.end - base if args.end is not None else len(data))
        addrs = [i.addr for i in linear_sweep(data, start, end)]
        reached = {i.addr: i for i in linear_sweep(data, start, end)}

    lines: list[str] = []
    prev = None
    for a in addrs:
        ins = reached[a]
        if prev is not None and a > prev:
            lines.append(f"  {prev:04X}: {'':11} ; ---- gap {prev:04X}..{a-1:04X} ----")
        lines.append(f"  {a:04X}: {ins.raw.hex(' ').upper():<11} {ins.mnemonic}")
        prev = a + ins.length

    out = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"wrote {len(lines)} lines to {args.out}", file=sys.stderr)
    else:
        print(out, end="")


def cmd_xref(args) -> None:
    data = load(args.file)
    ins_list = linear_sweep(data)
    calls: dict[int, list[int]] = defaultdict(list)
    dptr: dict[int, list[int]] = defaultdict(list)
    for ins in ins_list:
        if ins.target is not None and (ins.is_call or ins.is_jump):
            calls[ins.target].append(ins.addr)
        if ins.dptr is not None:
            dptr[ins.dptr].append(ins.addr)

    print(f"{len(calls)} distinct call/jump targets")
    print("\n-- call targets (LCALL/ACALL) --")
    for t in sorted(calls):
        ins = next(i for i in ins_list if i.addr == t) if any(i.addr == t for i in ins_list) else None
        frm = calls[t]
        n_call = sum(1 for a in frm for i in ins_list if i.addr == a and i.is_call)
        print(f"  0x{t:04X}  refs={len(frm):<4} first=0x{frm[0]:04X}")

    print("\n-- data pointer targets (MOV DPTR,#imm) grouping --")
    buckets = Counter()
    for t, refs in dptr.items():
        hi = t & 0xFF00
        buckets[hi] += len(refs)
    for hi, c in sorted(buckets.items()):
        print(f"  0x{hi:04X}xx  {c} refs")


def cmd_sfr(args) -> None:
    data = load(args.file)
    ins_list = linear_sweep(data)
    direct = Counter()
    bits = Counter()
    for ins in ins_list:
        if ins.direct is not None and ins.direct >= 0x80:
            direct[ins.direct] += 1
        if ins.op in (0x0B,):  # not a bit op; handled below
            pass
    # bit operands: re-scan textually for resolved names
    for ins in ins_list:
        for tok in ins.mnemonic.replace(",", " ").split():
            if "." in tok and tok.split(".")[0].isidentifier() and tok.split(".")[1].isdigit():
                bits[tok] += 1

    print("SFR writes/reads (direct addressing of 0x80..0xFF), count>=2:")
    for v, c in sorted(direct.items(), key=lambda kv: -kv[1]):
        if c < 2:
            continue
        print(f"  0x{v:02X} {dir_name(v):<12} x{c}")

    print("\nbit usage:")
    for name, c in bits.most_common():
        print(f"  {name:<14} x{c}")


def cmd_xdata(args) -> None:
    """MOVX accesses: on SH68F9x, DPTR 0xFF00+ is the extended SFR bank."""
    data = load(args.file)
    ins_list = linear_sweep(data)
    dptr = None
    xs: dict[int, list[int]] = defaultdict(list)
    unknown = 0
    for ins in ins_list:
        if ins.dptr is not None:
            dptr = ins.dptr
        if ins.op in (0xE0, 0xF0):     # MOVX A,@DPTR / MOVX @DPTR,A
            if dptr is None:
                unknown += 1
                continue
            xs[dptr].append(ins.addr)
    print(f"MOVX with statically-known DPTR: {sum(len(v) for v in xs.values())} sites, {unknown} unknown")
    print("\n  DPTR      count  kind")
    for t in sorted(xs):
        if t >= 0xFF00:
            kind = f"XSFR  {xsfr_name(t)}"
        elif t < 0x1000:
            kind = "XRAM (internal)"
        elif t < 0x1100:
            kind = "XROM (information block / FAC)"
        else:
            kind = "USB buffer / XRAM"
        print(f"  0x{t:04X}   {len(xs[t]):<5}  {kind}   first=0x{xs[t][0]:04X}")


def cmd_strings(args) -> None:
    data = load(args.file)
    base = args.base
    minlen = args.min
    out = []
    start = -1
    for i in range(len(data) + 1):
        c = data[i] if i < len(data) else 0
        if 0x20 <= c < 0x7F:
            if start < 0:
                start = i
            continue
        if start >= 0 and i - start >= minlen:
            out.append((base + start, data[start:i].decode("latin1")))
        start = -1
    print(f"{len(out)} strings (>= {minlen} chars):")
    for a, s in out:
        print(f"  {a:04X}  {s!r}")


def cmd_find(args) -> None:
    data = load(args.file)
    base = args.base
    pat = bytes(int(t, 16) for t in args.pattern.replace(",", " ").split())
    hits = []
    i = 0
    while True:
        i = data.find(pat, i)
        if i < 0:
            break
        hits.append(i)
        i += 1
    print(f"pattern {pat.hex(' ').upper()} ({len(pat)} bytes): {len(hits)} hit(s)")
    for off in hits[:args.limit]:
        print(f"  {base+off:04X}")
    if len(hits) > args.limit:
        print(f"  ... {len(hits) - args.limit} more")


def cmd_ports(args) -> None:
    """Report every code site that touches a port / pin-configuration register."""
    data = load(args.file)
    ins_list = linear_sweep(data)
    ports = {0x80: "P0", 0x90: "P1", 0x98: "P2", 0xA0: "P3", 0xB0: "P4",
             0x88: "P5", 0xC0: "P6", 0xF8: "P7"}
    cfg = {0xE1: "P0CR", 0xE2: "P1CR", 0xE3: "P2CR", 0xE4: "P3CR", 0xE5: "P4CR",
           0xE6: "P5CR", 0xE7: "P6CR", 0xD1: "P7CR", 0xE9: "P0PCR", 0xEA: "P1PCR",
           0xEB: "P2PCR", 0xEC: "P3PCR", 0xED: "P4PCR", 0xEE: "P5PCR", 0xEF: "P6PCR",
           0xD9: "P7PCR", 0xA5: "P1DRV", 0xA6: "P2DRV", 0xBB: "P3DRV", 0x8D: "P5DRV",
           0x8C: "DRVCON", 0x8A: "MAPPING"}

    per_port: dict[str, list[str]] = {v: [] for v in list(ports.values()) + list(cfg.values())}
    for ins in ins_list:
        # direct-address form
        if ins.direct is not None:
            name = ports.get(ins.direct) or cfg.get(ins.direct)
            if name:
                per_port[name].append(f"{ins.addr:04X} {ins.mnemonic}")
        # bit form (SETB/CLR/JB/CPL Px.y ...)
        tok = ins.mnemonic.split()
        if len(tok) >= 2:
            t = tok[-1].rstrip(",")
            for pn in ports.values():
                if t.startswith(pn + "."):
                    per_port[pn].append(f"{ins.addr:04X} {ins.mnemonic}")
                    break
    for name, sites in per_port.items():
        if sites:
            print(f"\n== {name} ({len(sites)} sites) ==")
            for s in sites[:args.limit]:
                print("   " + s)
            if len(sites) > args.limit:
                print(f"   ... {len(sites)-args.limit} more")


def main() -> int:
    ap = argparse.ArgumentParser(prog="fwdis", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("file")
        p.add_argument("--base", type=lambda s: int(s, 0), default=0)

    p = sub.add_parser("info"); common(p)
    p.add_argument("--block", type=int, default=1024)

    p = sub.add_parser("dis"); common(p)
    p.add_argument("--start", type=lambda s: int(s, 0), default=0)
    p.add_argument("--len", type=lambda s: int(s, 0))
    p.add_argument("--end", type=lambda s: int(s, 0))
    p.add_argument("--reachable", action="store_true")
    p.add_argument("--out")

    for name, fn in (("xref", cmd_xref), ("sfr", cmd_sfr), ("xdata", cmd_xdata)):
        p = sub.add_parser(name); common(p)

    p = sub.add_parser("strings"); common(p)
    p.add_argument("--min", type=int, default=4)

    p = sub.add_parser("find"); common(p)
    p.add_argument("pattern", help="hex bytes, e.g. '75 F0 A5 74 5A 02 FF 00'")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("ports"); common(p)
    p.add_argument("--limit", type=int, default=400)

    args = ap.parse_args()
    {"info": cmd_info, "dis": cmd_dis, "xref": cmd_xref, "sfr": cmd_sfr,
     "xdata": cmd_xdata, "strings": cmd_strings, "find": cmd_find,
     "ports": cmd_ports}[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
