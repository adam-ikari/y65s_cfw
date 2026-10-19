"""MCS-51 (8051) disassembler + image helpers.

The YD-Y65S keyboard runs a Sino Wealth SH68F90-class 8051 core. This module is
a table-driven disassembler with enough structure (labels, xrefs, SFR naming)
to make a 60 KiB vendor image readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# SFR naming
# --------------------------------------------------------------------------
# Standard 8051 SFRs, plus the Sinowealth SH68F9x additions. Names marked with
# a trailing '?' are inferred from usage (documented names are not public); they
# are kept stable so cross-references stay readable across sessions.

# Authoritative names taken from the SMK project's SH68F90 header
# (tools/smk/src/sino51lib/sh68f90/sh68f90.h), which was produced by reverse
# engineering this exact part family. Kept verbatim so analysis and any ported
# firmware agree on the same register names.
SFR_NAMES: dict[int, str] = {
    # CPU
    0xE0: "ACC", 0xF0: "B", 0xF1: "AUXC", 0xD0: "PSW", 0x81: "SP",
    0x82: "DPL", 0x83: "DPH", 0x84: "DPL1", 0x85: "DPH1", 0x86: "INSCON",
    # power
    0x87: "PCON", 0x8E: "SUSLO",
    # flash / ISP programming
    0xFB: "IB_OFFSET", 0xFC: "IB_DATA", 0xF2: "IB_CON1", 0xF3: "IB_CON2",
    0xF4: "IB_CON3", 0xF5: "IB_CON4", 0xF6: "IB_CON5", 0xF7: "XPAGE",
    0xA7: "FLASHCON",
    # watchdog / reset status
    0xB1: "RSTSTAT",
    # system clock
    0xB2: "CLKCON", 0xBC: "PLLCON", 0xBD: "CLKLO", 0xBE: "CLKRC0L",
    0xC6: "CLKRC0H", 0xBF: "CLKRC1L", 0xC7: "CLKRC1H",
    # interrupts
    0xA8: "IEN0", 0xA9: "IEN1", 0xB8: "IPL0", 0xB9: "IPL1", 0xB4: "IPH0",
    0xB5: "IPH1", 0xB6: "EXF0", 0xE8: "EXF1", 0xBA: "IENC", 0x8B: "EXCON",
    # EUART
    0xD8: "SCON", 0xAA: "SBUF", 0xAB: "SADDR", 0xAC: "SADEN", 0xAD: "SBRTH",
    0xAE: "SBRTL", 0xAF: "SFINE",
    # timer2
    0xC8: "T2CON", 0xC9: "T2MOD", 0xCA: "RCAP2L", 0xCB: "RCAP2H", 0xCC: "TL2",
    0xCD: "TH2",
    # SPI
    0xA2: "SPCON", 0xA1: "SPSTA", 0xA3: "SPDAT",
    # regulator
    0x8F: "REGCON",
    # USB
    0x91: "USBCON", 0x92: "USBIF1", 0x93: "USBIF2", 0x94: "USBIE1",
    0x95: "USBIE2", 0x96: "USBADDR", 0x97: "EP0CON", 0x99: "EP1CON",
    0x9A: "EP2CON", 0x9B: "IEP0CNT", 0x9C: "IEP1CNT", 0x9D: "IEP2CNT",
    0x9E: "OEP0CNT", 0x9F: "OEP1CNT", 0xA4: "OEP2CNT",
    # low power detect + drive option + mapping
    0xB3: "LPDCON", 0x89: "LPDSEL", 0x8C: "DRVCON", 0xA5: "P1DRV", 0xA6: "P2DRV",
    0xBB: "P3DRV", 0x8D: "P5DRV", 0x8A: "MAPPING",
    # PWM4 lives in the normal SFR space
    0xDA: "PWM40CON", 0xDB: "PWM41CON", 0xDC: "PWM42CON",
    0xDD: "PWM4PERDL", 0xDE: "PWM4PERDH",
    0xD2: "PWM40DUTY1L", 0xD3: "PWM41DUTY1L", 0xD4: "PWM42DUTY1L",
    0xD5: "PWM40DUTY1H", 0xD6: "PWM41DUTY1H", 0xD7: "PWM42DUTY1H",
    0xCE: "PWM40DUTY2L", 0xC1: "PWM41DUTY2L", 0xC2: "PWM42DUTY2L",
    0xC3: "PWM40DUTY2H", 0xC4: "PWM41DUTY2H", 0xC5: "PWM42DUTY2H",
    # ports
    0x80: "P0", 0x90: "P1", 0x98: "P2", 0xA0: "P3", 0xB0: "P4", 0x88: "P5",
    0xC0: "P6", 0xF8: "P7",
    # port mode configuration
    0xE1: "P0CR", 0xE2: "P1CR", 0xE3: "P2CR", 0xE4: "P3CR", 0xE5: "P4CR",
    0xE6: "P5CR", 0xE7: "P6CR", 0xD1: "P7CR",
    0xE9: "P0PCR", 0xEA: "P1PCR", 0xEB: "P2PCR", 0xEC: "P3PCR", 0xED: "P4PCR",
    0xEE: "P5PCR", 0xEF: "P6PCR", 0xD9: "P7PCR",
    # standard 8051 timers
    0x88 + 0x00: "P5", 0x89: "LPDSEL", 0x8A: "MAPPING",
}

# XSFR (extended register bank reached through MOVX @DPTR with DPTR >= 0xFF00)
XSFR_NAMES: dict[int, str] = {}
for _b in range(4):
    for _c in range(6):
        XSFR_NAMES[0xFF80 + _b * 6 + _c] = f"PWM{_b}{_c}CON"
    XSFR_NAMES[0xFF98 + _b] = f"PWM{_b}PERDL"
    XSFR_NAMES[0xFF9C + _b] = f"PWM{_b}PERDH"
    for _c in range(6):
        XSFR_NAMES[0xFFA0 + _b * 8 + _c] = f"PWM{_b}{_c}DUTY1L"
        XSFR_NAMES[0xFFB8 + _b * 8 + _c] = f"PWM{_b}{_c}DUTY1H"
        XSFR_NAMES[0xFFD0 + _b * 8 + _c] = f"PWM{_b}{_c}DUTY2L"
        XSFR_NAMES[0xFFE8 + _b * 8 + _c] = f"PWM{_b}{_c}DUTY2H"
XSFR_NAMES[0xFF00] = "ISP_ENTRY"


def xsfr_name(v: int) -> str:
    return XSFR_NAMES.get(v, f"XSFR_{v:04X}")


BIT_REG_BASE: dict[int, str] = {
    0x80: "P0", 0x88: "P5", 0x90: "P1", 0x98: "P2", 0xA0: "P3", 0xA8: "IEN0",
    0xB0: "P4", 0xB8: "IPL0", 0xC0: "P6", 0xC8: "T2CON", 0xD0: "PSW",
    0xD8: "SCON", 0xE0: "ACC", 0xE8: "EXF1", 0xF0: "B", 0xF8: "P7",
}


def dir_name(v: int) -> str:
    if v in SFR_NAMES:
        return SFR_NAMES[v]
    return f"RAM_{v:02X}" if v < 0x80 else f"SFR_{v:02X}"


def bit_name(v: int | None) -> str:
    if v is None:
        return "?"
    base = BIT_REG_BASE.get(v & 0xF8)
    return f"{base}.{v & 7}" if base else (f"BITS_{v:02X}" if v < 0x80 else f"BIT_{v:02X}")


# --------------------------------------------------------------------------
# Opcode table: (mnemonic, operand-kind, length)
# --------------------------------------------------------------------------
# operand kinds:
#   none, a          - no operand / implicit A
#   i  d  r  c  b    - #imm, direct, rel, addr16, bit
#   a11              - 11-bit page address
#   da dd di d_r     - direct,A | direct,direct | direct,#imm | direct,rel
#   i_r br bc nb     - #imm,rel | bit,rel | bit,C | /bit
#   dr               - direct,rel (DJNZ)

_REG = [f"R{i}" for i in range(8)]
TABLE: dict[int, tuple[str, str, int]] = {}


def _d(op: int, mnem: str, kind: str, ln: int) -> None:
    TABLE[op] = (mnem, kind, ln)


_d(0x00, "NOP", "none", 1)
_d(0x01, "AJMP", "a11", 2)
_d(0x02, "LJMP", "c", 3)
_d(0x03, "RR A", "none", 1)
_d(0x04, "INC A", "none", 1)
_d(0x05, "INC", "d", 2)
_d(0x06, "INC @R0", "none", 1)
_d(0x07, "INC @R1", "none", 1)
for _i in range(8):
    _d(0x08 + _i, f"INC {_REG[_i]}", "none", 1)

_d(0x10, "JBC", "br", 3)
_d(0x11, "ACALL", "a11", 2)
_d(0x12, "LCALL", "c", 3)
_d(0x13, "RRC A", "none", 1)
_d(0x14, "DEC A", "none", 1)
_d(0x15, "DEC", "d", 2)
_d(0x16, "DEC @R0", "none", 1)
_d(0x17, "DEC @R1", "none", 1)
for _i in range(8):
    _d(0x18 + _i, f"DEC {_REG[_i]}", "none", 1)

_d(0x20, "JB", "br", 3)
_d(0x21, "AJMP", "a11", 2)
_d(0x22, "RET", "none", 1)
_d(0x23, "RL A", "none", 1)
_d(0x24, "ADD A,", "i", 2)
_d(0x25, "ADD A,", "d", 2)
_d(0x26, "ADD A,@R0", "none", 1)
_d(0x27, "ADD A,@R1", "none", 1)
for _i in range(8):
    _d(0x28 + _i, f"ADD A,{_REG[_i]}", "none", 1)

_d(0x30, "JNB", "br", 3)
_d(0x31, "ACALL", "a11", 2)
_d(0x32, "RETI", "none", 1)
_d(0x33, "RLC A", "none", 1)
_d(0x34, "ADDC A,", "i", 2)
_d(0x35, "ADDC A,", "d", 2)
_d(0x36, "ADDC A,@R0", "none", 1)
_d(0x37, "ADDC A,@R1", "none", 1)
for _i in range(8):
    _d(0x38 + _i, f"ADDC A,{_REG[_i]}", "none", 1)

_d(0x40, "JC", "r", 2)
_d(0x41, "AJMP", "a11", 2)
_d(0x42, "ORL", "da", 2)
_d(0x43, "ORL", "di", 3)
_d(0x44, "ORL A,", "i", 2)
_d(0x45, "ORL A,", "d", 2)
_d(0x46, "ORL A,@R0", "none", 1)
_d(0x47, "ORL A,@R1", "none", 1)
for _i in range(8):
    _d(0x48 + _i, f"ORL A,{_REG[_i]}", "none", 1)

_d(0x50, "JNC", "r", 2)
_d(0x51, "ACALL", "a11", 2)
_d(0x52, "ANL", "da", 2)
_d(0x53, "ANL", "di", 3)
_d(0x54, "ANL A,", "i", 2)
_d(0x55, "ANL A,", "d", 2)
_d(0x56, "ANL A,@R0", "none", 1)
_d(0x57, "ANL A,@R1", "none", 1)
for _i in range(8):
    _d(0x58 + _i, f"ANL A,{_REG[_i]}", "none", 1)

_d(0x60, "JZ", "r", 2)
_d(0x61, "AJMP", "a11", 2)
_d(0x62, "XRL", "da", 2)
_d(0x63, "XRL", "di", 3)
_d(0x64, "XRL A,", "i", 2)
_d(0x65, "XRL A,", "d", 2)
_d(0x66, "XRL A,@R0", "none", 1)
_d(0x67, "XRL A,@R1", "none", 1)
for _i in range(8):
    _d(0x68 + _i, f"XRL A,{_REG[_i]}", "none", 1)

_d(0x70, "JNZ", "r", 2)
_d(0x71, "ACALL", "a11", 2)
_d(0x72, "ORL C,", "b", 2)
_d(0x73, "JMP @A+DPTR", "none", 1)
_d(0x74, "MOV A,", "i", 2)
_d(0x75, "MOV", "di", 3)
_d(0x76, "MOV @R0,", "i", 2)
_d(0x77, "MOV @R1,", "i", 2)
for _i in range(8):
    _d(0x78 + _i, f"MOV {_REG[_i]},", "i", 2)

_d(0x80, "SJMP", "r", 2)
_d(0x81, "AJMP", "a11", 2)
_d(0x82, "ANL C,", "b", 2)
_d(0x83, "MOVC A,@A+PC", "none", 1)
_d(0x84, "DIV AB", "none", 1)
_d(0x85, "MOV", "dd", 3)
_d(0x86, "MOV", "d_at0", 2)
_d(0x87, "MOV", "d_at1", 2)
for _i in range(8):
    _d(0x88 + _i, f"MOV|{_i}", "drn", 2)

_d(0x90, "MOV DPTR,", "c", 3)
_d(0x91, "ACALL", "a11", 2)
_d(0x92, "MOV", "bc", 2)
_d(0x93, "MOVC A,@A+DPTR", "none", 1)
_d(0x94, "SUBB A,", "i", 2)
_d(0x95, "SUBB A,", "d", 2)
_d(0x96, "SUBB A,@R0", "none", 1)
_d(0x97, "SUBB A,@R1", "none", 1)
for _i in range(8):
    _d(0x98 + _i, f"SUBB A,{_REG[_i]}", "none", 1)

_d(0xA0, "ORL C,/", "b", 2)
_d(0xA1, "AJMP", "a11", 2)
_d(0xA2, "MOV C,", "b", 2)
_d(0xA3, "INC DPTR", "none", 1)
_d(0xA4, "MUL AB", "none", 1)
_d(0xA5, "(reserved)", "none", 1)
_d(0xA6, "MOV @R0,", "d", 2)
_d(0xA7, "MOV @R1,", "d", 2)
for _i in range(8):
    _d(0xA8 + _i, f"MOV {_REG[_i]},", "d", 2)

_d(0xB0, "ANL C,/", "b", 2)
_d(0xB1, "ACALL", "a11", 2)
_d(0xB2, "CPL", "b", 2)
_d(0xB3, "CPL C", "none", 1)
_d(0xB4, "CJNE A,", "i_r", 3)
_d(0xB5, "CJNE A,", "d_r", 3)
_d(0xB6, "CJNE @R0,", "i_r", 3)
_d(0xB7, "CJNE @R1,", "i_r", 3)
for _i in range(8):
    _d(0xB8 + _i, f"CJNE {_REG[_i]},", "i_r", 3)

_d(0xC0, "PUSH", "d", 2)
_d(0xC1, "AJMP", "a11", 2)
_d(0xC2, "CLR", "b", 2)
_d(0xC3, "CLR C", "none", 1)
_d(0xC4, "SWAP A", "none", 1)
_d(0xC5, "XCH A,", "d", 2)
_d(0xC6, "XCH A,@R0", "none", 1)
_d(0xC7, "XCH A,@R1", "none", 1)
for _i in range(8):
    _d(0xC8 + _i, f"XCH A,{_REG[_i]}", "none", 1)

_d(0xD0, "POP", "d", 2)
_d(0xD1, "ACALL", "a11", 2)
_d(0xD2, "SETB", "b", 2)
_d(0xD3, "SETB C", "none", 1)
_d(0xD4, "DA A", "none", 1)
_d(0xD5, "DJNZ", "dr", 3)
_d(0xD6, "XCHD A,@R0", "none", 1)
_d(0xD7, "XCHD A,@R1", "none", 1)
for _i in range(8):
    _d(0xD8 + _i, f"DJNZ {_REG[_i]},", "r", 2)

_d(0xE0, "MOVX A,@DPTR", "none", 1)
_d(0xE1, "AJMP", "a11", 2)
_d(0xE2, "MOVX A,@R0", "none", 1)
_d(0xE3, "MOVX A,@R1", "none", 1)
_d(0xE4, "CLR A", "none", 1)
_d(0xE5, "MOV A,", "d", 2)
_d(0xE6, "MOV A,@R0", "none", 1)
_d(0xE7, "MOV A,@R1", "none", 1)
for _i in range(8):
    _d(0xE8 + _i, f"MOV A,{_REG[_i]}", "none", 1)

_d(0xF0, "MOVX @DPTR,A", "none", 1)
_d(0xF1, "ACALL", "a11", 2)
_d(0xF2, "MOVX @R0,A", "none", 1)
_d(0xF3, "MOVX @R1,A", "none", 1)
_d(0xF4, "CPL A", "none", 1)
_d(0xF5, "MOV", "da", 2)
_d(0xF6, "MOV @R0,A", "none", 1)
_d(0xF7, "MOV @R1,A", "none", 1)
for _i in range(8):
    _d(0xF8 + _i, f"MOV {_REG[_i]},A", "none", 1)


@dataclass
class Instr:
    addr: int
    raw: bytes
    mnemonic: str
    op: int
    length: int
    target: int | None = None      # branch/call target
    direct: int | None = None      # direct-address operand
    imm: int | None = None         # immediate operand
    dptr: int | None = None        # MOV DPTR,#imm16
    indirect: bool = False         # target address is computed (JMP @A+DPTR)
    is_call: bool = False
    is_jump: bool = False
    is_cond: bool = False
    is_return: bool = False

    @property
    def text(self) -> str:
        return self.mnemonic


def disasm_one(buf: bytes, addr: int) -> Instr:
    """Decode the instruction at *buf*[addr] (address == offset)."""
    op = buf[addr]
    mnem, kind, ln = TABLE.get(op, ("DB", "db", 1))
    n1 = buf[addr + 1] if addr + 1 < len(buf) else 0
    n2 = buf[addr + 2] if addr + 2 < len(buf) else 0
    raw = bytes(buf[addr:addr + ln])

    def rel(v: int) -> int:
        return addr + 2 + v if v < 0x80 else addr + 2 + v - 256

    ins = Instr(addr=addr, raw=raw, mnemonic="", op=op, length=ln)
    if kind == "none":
        text = mnem
    elif kind == "i":
        text = f"{mnem} #{n1:02X}"
        ins.imm = n1
    elif kind == "d":
        text = f"{mnem} {dir_name(n1)}"
        ins.direct = n1
    elif kind == "da":
        text = f"{mnem} {dir_name(n1)},A"
        ins.direct = n1
        if mnem == "MOV":
            text = f"MOV {dir_name(n1)},A"
    elif kind == "di":
        text = f"{mnem} {dir_name(n1)},#{n2:02X}"
        ins.direct = n1
        ins.imm = n2
    elif kind == "dd":
        text = f"{mnem} {dir_name(n2)},{dir_name(n1)}"
        ins.direct = n1
    elif kind == "d_at0":
        text = f"{mnem} {dir_name(n1)},@R0"
        ins.direct = n1
    elif kind == "d_at1":
        text = f"{mnem} {dir_name(n1)},@R1"
        ins.direct = n1
    elif kind == "c":
        t = (n1 << 8) | n2
        ins.target = t
        if mnem.startswith("MOV DPTR"):
            ins.dptr = t
            text = f"MOV DPTR,#0x{t:04X}"
        else:
            text = f"{mnem} 0x{t:04X}"
            ins.is_call = mnem in ("LCALL",)
            ins.is_jump = mnem in ("LJMP",)
    elif kind == "a11":
        t = ((addr + 2) & 0xF800) | (((op >> 5) & 7) << 8) | n1
        ins.target = t
        ins.is_call = mnem == "ACALL"
        ins.is_jump = mnem == "AJMP"
        text = f"{mnem} 0x{t:04X}"
    elif kind == "r":
        t = rel(n1)
        ins.target = t
        text = f"{mnem} 0x{t:04X}"
        ins.is_jump = True
        ins.is_cond = mnem in ("JZ", "JNZ", "JC", "JNC")
    elif kind == "dr":
        t = rel(n2)
        ins.target = t
        ins.direct = n1
        text = f"{mnem} {dir_name(n1)},0x{t:04X}"
        ins.is_cond = True
    elif kind == "i_r":
        t = rel(n2)
        ins.target = t
        ins.imm = n1
        text = f"{mnem}#{n1:02X},0x{t:04X}"
        ins.is_cond = True
    elif kind == "d_r":
        t = rel(n2)
        ins.target = t
        ins.direct = n1
        text = f"{mnem}{dir_name(n1)},0x{t:04X}"
        ins.is_cond = True
    elif kind == "drn":
        # MOV direct,Rn
        reg = int(mnem.split("|")[1])
        text = f"MOV {dir_name(n1)}, {_REG[reg]}"
        ins.direct = n1
    elif kind == "b":
        text = f"{mnem} {bit_name(n1)}"
    elif kind == "bc":
        text = f"{mnem} {bit_name(n1)},C"
    elif kind == "br":
        t = rel(n2)
        ins.target = t
        text = f"{mnem} {bit_name(n1)},0x{t:04X}"
        ins.is_cond = True
    elif kind == "db":
        text = f"DB 0x{op:02X}"
    else:
        text = f"{mnem} ???"
    ins.mnemonic = text.replace(",", ", ") if False else text
    if mnem in ("RET", "RETI"):
        ins.is_return = True
    if mnem == "JMP @A+DPTR":
        ins.indirect = True
    return ins


def linear_sweep(buf: bytes, start: int = 0, end: int | None = None) -> list[Instr]:
    end = len(buf) if end is None else end
    out: list[Instr] = []
    a = start
    while a < end:
        ins = disasm_one(buf, a)
        out.append(ins)
        a += ins.length
    return out


def recursive_traverse(buf: bytes, seeds: list[int]) -> dict[int, Instr]:
    """Follow control flow from *seeds*, returning reachable instructions."""
    seen: dict[int, Instr] = {}
    stack = list(seeds)
    while stack:
        a = stack.pop()
        while 0 <= a < len(buf) and a not in seen:
            ins = disasm_one(buf, a)
            seen[a] = ins
            if ins.target is not None:
                stack.append(ins.target)
            if ins.is_call or ins.is_jump or ins.is_cond:
                if ins.is_cond:
                    a += ins.length          # fall through
                    continue
                break
            if ins.is_return or ins.indirect:
                break
            a += ins.length
    return seen


# --------------------------------------------------------------------------
# Intel HEX (needed to rebuild a flashable payload)
# --------------------------------------------------------------------------

def to_ihex(data: bytes, base: int = 0) -> str:
    lines: list[str] = []

    def rec(rec_type: int, offset: int, payload: bytes) -> None:
        count = len(payload)
        b = bytes([count, (offset >> 8) & 0xFF, offset & 0xFF, rec_type]) + payload
        checksum = (-sum(b)) & 0xFF
        lines.append(":" + b.hex().upper() + f"{checksum:02X}")

    if base:
        rec(4, 0, bytes([(base >> 8) & 0xFF, base & 0xFF]))
    addr = 0
    while addr < len(data):
        chunk = data[addr:addr + 16]
        rec(0, (base + addr) & 0xFFFF, chunk)
        addr += 16
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def from_ihex(text: str) -> bytes:
    out = bytearray()
    upper = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        count, off_hi, off_lo, rtype = raw[0], raw[1], raw[2], raw[3]
        payload = raw[4:4 + count]
        off = (off_hi << 8) | off_lo
        if rtype == 0:
            if upper + off + count > len(out):
                out.extend(b"\xFF" * (upper + off + count - len(out)))
            out[upper + off:upper + off + count] = payload
        elif rtype == 1:
            break
        elif rtype == 2:
            upper = ((payload[0] << 8) | payload[1]) << 4
        elif rtype == 4:
            upper = ((payload[0] << 8) | payload[1]) << 16
    return bytes(out)
