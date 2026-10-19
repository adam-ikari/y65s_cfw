#!/usr/bin/env node
// dis8051.js — accurate table-driven MCS-51 / 8051 disassembler + analysis helpers.
//
// Usage:
//   node dis8051.js <file.bin> [--base 0x0] [--start 0x0] [--len 0x100 | --end 0x400]
//                             [--sfr]      SFR / direct-address usage report
//                             [--xref]     call/jump/data-pointer cross references
//                             [--tables]   MOVC/DMOV table bases
const fs = require('fs');

// ---------------------------------------------------------------------------
// Operand kinds
//   none - no operand        A    - accumulator (implicit)
//   d    - direct (1B)       i    - immediate (1B)
//   r    - relative (1B)     c    - 16-bit code address
//   b    - bit address (1B)  a11  - 11-bit page address
//   dd   - direct,direct     di   - direct,#imm
//   br   - bit,rel           dr   - direct,rel
//   d1r  - direct,rel (2B operand)  rn_i - Rn,#imm
//   ci   - CJNE combos handled explicitly
// ---------------------------------------------------------------------------
const REG = ['R0', 'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7'];
const T = [];
const def = (op, mnem, kind) => { T[op] = { mnem, kind }; };
const defBank = (hi, fmt) => { for (let lo = 8; lo < 16; lo++) def(hi * 16 + lo, fmt(REG[lo - 8]), 'A'); };

def(0x00, 'NOP', 'none');
def(0x01, 'AJMP', 'a11');
def(0x02, 'LJMP', 'c');
def(0x03, 'RR', 'Aacc');
def(0x04, 'INC', 'Aacc');
def(0x05, 'INC', 'd');
def(0x06, 'INC', '@R0');
def(0x07, 'INC', '@R1');
defBank(0x0, (r) => `INC ${r}`);

def(0x10, 'JBC', 'br');
def(0x11, 'ACALL', 'a11');
def(0x12, 'LCALL', 'c');
def(0x13, 'RRC', 'Aacc');
def(0x14, 'DEC', 'Aacc');
def(0x15, 'DEC', 'd');
def(0x16, 'DEC', '@R0');
def(0x17, 'DEC', '@R1');
defBank(0x1, (r) => `DEC ${r}`);

def(0x20, 'JB', 'br');
def(0x21, 'AJMP', 'a11');
def(0x22, 'RET', 'none');
def(0x23, 'RL', 'Aacc');
def(0x24, 'ADD A', 'i');
def(0x25, 'ADD A', 'd');
def(0x26, 'ADD A', '@R0');
def(0x27, 'ADD A', '@R1');
defBank(0x2, (r) => `ADD A,${r}`);

def(0x30, 'JNB', 'br');
def(0x31, 'ACALL', 'a11');
def(0x32, 'RETI', 'none');
def(0x33, 'RLC', 'Aacc');
def(0x34, 'ADDC A', 'i');
def(0x35, 'ADDC A', 'd');
def(0x36, 'ADDC A', '@R0');
def(0x37, 'ADDC A', '@R1');
defBank(0x3, (r) => `ADDC A,${r}`);

def(0x40, 'JC', 'r');
def(0x41, 'AJMP', 'a11');
def(0x42, 'ORL', 'da');            // ORL direct,A
def(0x43, 'ORL', 'di');
def(0x44, 'ORL A', 'i');
def(0x45, 'ORL A', 'd');
def(0x46, 'ORL A', '@R0');
def(0x47, 'ORL A', '@R1');
defBank(0x4, (r) => `ORL A,${r}`);

def(0x50, 'JNC', 'r');
def(0x51, 'ACALL', 'a11');
def(0x52, 'ANL', 'da');
def(0x53, 'ANL', 'di');
def(0x54, 'ANL A', 'i');
def(0x55, 'ANL A', 'd');
def(0x56, 'ANL A', '@R0');
def(0x57, 'ANL A', '@R1');
defBank(0x5, (r) => `ANL A,${r}`);

def(0x60, 'JZ', 'r');
def(0x61, 'AJMP', 'a11');
def(0x62, 'XRL', 'da');
def(0x63, 'XRL', 'di');
def(0x64, 'XRL A', 'i');
def(0x65, 'XRL A', 'd');
def(0x66, 'XRL A', '@R0');
def(0x67, 'XRL A', '@R1');
defBank(0x6, (r) => `XRL A,${r}`);

def(0x70, 'JNZ', 'r');
def(0x71, 'ACALL', 'a11');
def(0x72, 'ORL C', 'b');
def(0x73, 'JMP @A+DPTR', 'none');
def(0x74, 'MOV A', 'i');
def(0x75, 'MOV', 'di');
def(0x76, 'MOV @R0', 'i');
def(0x77, 'MOV @R1', 'i');
defBank(0x7, (r) => `MOV ${r}`);   // MOV Rn,#imm

def(0x80, 'SJMP', 'r');
def(0x81, 'AJMP', 'a11');
def(0x82, 'ANL C', 'b');
def(0x83, 'MOVC A,@A+PC', 'none');
def(0x84, 'DIV AB', 'none');
def(0x85, 'MOV', 'dd');
def(0x86, 'MOV', 'd@0');
def(0x87, 'MOV', 'd@1');
defBank(0x8, (r) => `MOV ${r}`);   // MOV direct,Rn

def(0x90, 'MOV DPTR', 'c');
def(0x91, 'ACALL', 'a11');
def(0x92, 'MOV', 'bc');            // MOV bit,C
def(0x93, 'MOVC A,@A+DPTR', 'none');
def(0x94, 'SUBB A', 'i');
def(0x95, 'SUBB A', 'd');
def(0x96, 'SUBB A', '@R0');
def(0x97, 'SUBB A', '@R1');
defBank(0x9, (r) => `SUBB A,${r}`);

def(0xa0, 'ORL C', 'nb');          // ORL C,/bit
def(0xa1, 'AJMP', 'a11');
def(0xa2, 'MOV C', 'b');
def(0xa3, 'INC DPTR', 'none');
def(0xa4, 'MUL AB', 'none');
def(0xa5, '???', 'none');          // reserved
def(0xa6, 'MOV @R0', 'd');
def(0xa7, 'MOV @R1', 'd');
defBank(0xa, (r) => `MOV ${r}`);   // MOV Rn,direct

def(0xb0, 'ANL C', 'nb');
def(0xb1, 'ACALL', 'a11');
def(0xb2, 'CPL', 'b');
def(0xb3, 'CPL C', 'none');
def(0xb4, 'CJNE A', 'i_r');
def(0xb5, 'CJNE A', 'd_r');
def(0xb6, 'CJNE @R0', 'i_r');
def(0xb7, 'CJNE @R1', 'i_r');
for (let lo = 8; lo < 16; lo++) def(0xb0 + lo, `CJNE ${REG[lo - 8]}`, 'i_r');

def(0xc0, 'PUSH', 'd');
def(0xc1, 'AJMP', 'a11');
def(0xc2, 'CLR', 'b');
def(0xc3, 'CLR C', 'none');
def(0xc4, 'SWAP A', 'none');
def(0xc5, 'XCH A', 'd');
def(0xc6, 'XCH A', '@R0');
def(0xc7, 'XCH A', '@R1');
defBank(0xc, (r) => `XCH A,${r}`);

def(0xd0, 'POP', 'd');
def(0xd1, 'ACALL', 'a11');
def(0xd2, 'SETB', 'b');
def(0xd3, 'SETB C', 'none');
def(0xd4, 'DA A', 'none');
def(0xd5, 'DJNZ', 'dr');
def(0xd6, 'XCHD A,@R0', 'none');
def(0xd7, 'XCHD A,@R1', 'none');
for (let lo = 8; lo < 16; lo++) def(0xd0 + lo, `DJNZ ${REG[lo - 8]}`, 'r');

def(0xe0, 'MOVX A,@DPTR', 'none');
def(0xe1, 'AJMP', 'a11');
def(0xe2, 'MOVX A,@R0', 'none');
def(0xe3, 'MOVX A,@R1', 'none');
def(0xe4, 'CLR A', 'none');
def(0xe5, 'MOV A', 'd');
def(0xe6, 'MOV A,@R0', 'none');
def(0xe7, 'MOV A,@R1', 'none');
defBank(0xe, (r) => `MOV A,${r}`);

def(0xf0, 'MOVX @DPTR,A', 'none');
def(0xf1, 'ACALL', 'a11');
def(0xf2, 'MOVX @R0,A', 'none');
def(0xf3, 'MOVX @R1,A', 'none');
def(0xf4, 'CPL A', 'none');
def(0xf5, 'MOV', 'da');
def(0xf6, 'MOV @R0,A', 'none');
def(0xf7, 'MOV @R1,A', 'none');
defBank(0xf, (r) => `MOV ${r},A`);

// ---------------------------------------------------------------------------
// SFR naming. Standard 8051 + the Sinowealth SH68F9x family names documented in
// the community (SH68F8x/9x share the layout) and inferred from usage below.
const SFR = {
  0x80: 'P0', 0x81: 'SP', 0x82: 'DPL', 0x83: 'DPH', 0x84: 'DPL1', 0x85: 'DPH1', 0x86: 'DPS',
  0x87: 'PCON', 0x88: 'TCON', 0x89: 'TMOD', 0x8a: 'TL0', 0x8b: 'TL1', 0x8c: 'TH0', 0x8d: 'TH1',
  0x8e: 'CKCON', 0x8f: 'PWMCON?', 0x90: 'P1', 0x91: 'P1M1', 0x92: 'P1M2', 0x93: 'P1SRC?',
  0x94: 'P1DIR?', 0x95: 'P1PUR?', 0x96: 'P1OD?', 0x97: 'P1IEN1?', 0x98: 'SCON', 0x99: 'SBUF',
  0x9a: 'SVALID?', 0x9b: 'SALIGN?',
  0xa0: 'P2', 0xa1: 'P2M1', 0xa2: 'P2M2', 0xa8: 'IE', 0xa9: 'USBSTA', 0xaa: 'USBCTL',
  0xab: 'USBIE', 0xac: 'USBEP0C', 0xad: 'USBEP0S', 0xae: 'USBEP1C', 0xaf: 'USBEP1S',
  0xb0: 'P3', 0xb1: 'P3M1', 0xb2: 'P3M2', 0xb3: 'P3SRC?', 0xb4: 'P3DIR?', 0xb5: 'P3PUR?',
  0xb6: 'P3OD?', 0xb7: 'P3IEN1?', 0xb8: 'IP', 0xb9: 'SADDR', 0xba: 'SADEN',
  0xbb: 'PWM1L?', 0xbc: 'PWM1H?', 0xbd: 'PWM2L?', 0xbe: 'PWM2H?',
  0xc0: 'USBCON?', 0xc1: 'USBBAUD?', 0xc2: 'USBPIN?', 0xc3: 'USBADDR?', 0xc8: 'T2CON',
  0xc9: 'RCAP2L', 0xca: 'RCAP2H', 0xcb: 'TL2', 0xcc: 'TH2',
  0xd0: 'PSW', 0xd8: 'EIE', 0xd9: 'EIP1', 0xda: 'EIP2?', 0xdb: '?',
  0xe0: 'ACC', 0xe8: 'IE2?', 0xf0: 'B', 0xf8: 'IP2?',
  0x91: 'USBPIN?',
};
const bitRegBase = { 0x80: 'P0', 0x88: 'TCON', 0x90: 'P1', 0x98: 'SCON', 0xa0: 'P2', 0xa8: 'IE', 0xb0: 'P3', 0xb8: 'IP', 0xc0: 'USBCON?', 0xc8: 'T2CON', 0xd0: 'PSW', 0xd8: 'EIE', 0xe0: 'ACC', 0xf0: 'B', 0xf8: 'IP2?' };

function dirName(v) {
  if (SFR[v]) return SFR[v];
  return v < 0x80 ? `RAM_0x${v.toString(16).padStart(2, '0')}` : `SFR_0x${v.toString(16)}`;
}
function bitName(v) {
  const base = bitRegBase[v & 0xf8];
  return base ? `${base}.${v & 7}` : (v < 0x80 ? `BITS_0x${v.toString(16).padStart(2, '0')}` : `BIT_0x${v.toString(16)}`);
}

function disasm(buf, off, addr) {
  const op = buf[off];
  const e = T[op];
  if (!e) return { len: 1, text: `DB 0x${op.toString(16).padStart(2, '0')}` };
  const n = buf[off + 1], n2 = buf[off + 2];
  const rel = (v) => (v < 0x80 ? addr + 2 + v : addr + 2 + v - 256);
  const a11 = () => ((addr + 2) & 0xf800) | ((op >> 5 & 7) << 8) | n;
  switch (e.kind) {
    case 'none': return { len: 1, text: e.mnem };
    case 'Aacc': return { len: 1, text: `${e.mnem} A` };
    case 'i': return { len: 2, text: `${e.mnem},#0x${n.toString(16).padStart(2, '0')}` };
    case 'i_r': return { len: 3, text: `${e.mnem},#0x${n.toString(16).padStart(2, '0')},0x${rel(n2).toString(16)}` };
    case 'd': return { len: 2, text: `${e.mnem} ${dirName(n)}` };
    case 'da': return { len: 2, text: `${e.mnem} ${dirName(n)},A` };
    case 'd@0': return { len: 2, text: `${e.mnem} ${dirName(n)},@R0` };
    case 'd@1': return { len: 2, text: `${e.mnem} ${dirName(n)},@R1` };
    case 'di': return { len: 3, text: `${e.mnem} ${dirName(n)},#0x${n2.toString(16).padStart(2, '0')}` };
    case 'dd': return { len: 3, text: `${e.mnem} ${dirName(n2)},${dirName(n)}` };
    case 'c': return { len: 3, text: `${e.mnem},#0x${((n << 8) | n2).toString(16)}` };
    case 'r': return { len: 2, text: `${e.mnem} 0x${rel(n).toString(16)}` };
    case 'dr': return { len: 3, text: `${e.mnem} ${dirName(n)},0x${rel(n2).toString(16)}` };
    case 'b': return { len: 2, text: `${e.mnem} ${bitName(n)}` };
    case 'nb': return { len: 2, text: `${e.mnem} /${bitName(n)}` };
    case 'bc': return { len: 2, text: `${e.mnem} ${bitName(n)},C` };
    case 'br': return { len: 3, text: `${e.mnem} ${bitName(n)},0x${rel(n2).toString(16)}` };
    case 'a11': return { len: 2, text: `${e.mnem} 0x${a11().toString(16)}` };
    default: return { len: 1, text: `${e.mnem}` };
  }
}

// ---------------------------------------------------------------------------
const args = process.argv.slice(2);
const opt = { base: 0, start: 0, len: null, end: null, mode: 'dis' };
let file = null;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--base') opt.base = parseInt(args[++i], 16);
  else if (a === '--start') opt.start = parseInt(args[++i], 16);
  else if (a === '--len') opt.len = parseInt(args[++i], 16);
  else if (a === '--end') opt.end = parseInt(args[++i], 16);
  else if (a === '--sfr') opt.mode = 'sfr';
  else if (a === '--xref') opt.mode = 'xref';
  else if (a === '--tables') opt.mode = 'tables';
  else file = a;
}
const buf = fs.readFileSync(file);
const toOff = (a) => a - opt.base;
let start = opt.start;
let end = opt.end != null ? opt.end : (opt.len != null ? start + opt.len : opt.base + buf.length);

if (opt.mode === 'dis') {
  for (let a = start; a < end;) {
    const off = toOff(a);
    if (off < 0 || off >= buf.length) break;
    const { len, text } = disasm(buf, off, a);
    const bytes = [...buf.subarray(off, off + len)].map((x) => x.toString(16).padStart(2, '0')).join(' ');
    console.log(`  ${a.toString(16).padStart(4, '0')}: ${bytes.padEnd(11)} ${text}`);
    a += len;
  }
}

// Whole-image linear sweep collector (for the reports below)
function sweep() {
  const out = [];
  for (let a = opt.base; a < opt.base + buf.length;) {
    const off = toOff(a);
    const { len, text } = disasm(buf, off, a);
    out.push({ addr: a, off, len, text, op: buf[off] });
    a += len;
  }
  return out;
}

if (opt.mode === 'sfr') {
  const direct = new Map(), bits = new Map();
  for (const ins of sweep()) {
    const m = ins.text.match(/^(MOV|ANL|ORL|XRL|INC|DEC|PUSH|POP|XCH|SETB|CLR|CPL|JB|JNB|JBC|CJNE|DJNZ|MOVX)\b.*?\b(SFR_0x[0-9a-f]+|RAM_0x[0-9a-f]+|P[0-3]\b|[A-Z][A-Z0-9]{1,9})(?:,|$|\.)/);
    const mn = ins.text.split(' ')[0];
    // direct-address operands
    for (const dm of ins.text.matchAll(/\b(SFR_0x[0-9a-f]+|RAM_0x[0-9a-f]+)\b/g)) {
      const v = parseInt(dm[1].slice(-2), 16);
      direct.set(v, (direct.get(v) || 0) + 1);
    }
    for (const bm of ins.text.matchAll(/\bBIT_0x[0-9a-f]+\b|\b(BITS_0x[0-9a-f]+)\b/g)) {
      const v = parseInt(bm[0].slice(-2), 16);
      bits.set(v, (bits.get(v) || 0) + 1);
    }
  }
  console.log('direct-address usage (unresolved SFR_/RAM_ hex only), count >= 2:');
  [...direct.entries()].filter(([, c]) => c >= 2).sort((a, b) => b[1] - a[1])
    .forEach(([v, c]) => console.log(`  0x${v.toString(16).padStart(2, '0')} ${dirName(v).padEnd(12)} x${c}`));
  console.log('\nbit-address usage (resolved):');
  const bits2 = new Map();
  for (const ins of sweep()) {
    for (const bm of ins.text.matchAll(/\b([PBTAECIS0-9]?\w*)\.[0-7]\b/g)) {
      bits2.set(bm[0], (bits2.get(bm[0]) || 0) + 1);
    }
  }
  [...bits2.entries()].sort((a, b) => b[1] - a[1]).forEach(([k, c]) => console.log(`  ${k.padEnd(14)} x${c}`));
}

if (opt.mode === 'xref') {
  const calls = new Map(), dptrs = new Map(), movcs = [];
  for (const ins of sweep()) {
    const m = ins.text.match(/^(LCALL|LJMP|AJMP|ACALL|JMP) 0x([0-9a-f]+)$/);
    if (m) { const t = parseInt(m[2], 16); if (!calls.has(t)) calls.set(t, []); calls.get(t).push(ins.addr); }
    const d = ins.text.match(/^MOV DPTR,#0x([0-9a-f]+)$/);
    if (d) { const t = parseInt(d[1], 16); if (!dptrs.has(t)) dptrs.set(t, []); dptrs.get(t).push(ins.addr); }
    if (ins.text.startsWith('MOVC A,@A+DPTR')) movcs.push({ addr: ins.addr });
  }
  console.log('call/jump targets sorted by address:');
  [...calls.entries()].sort((a, b) => a[0] - b[0]).forEach(([t, from]) =>
    console.log(`  0x${t.toString(16).padStart(4, '0')}  <- ${from.length}x  first@0x${from[0].toString(16)}`));
  console.log('\nMOV DPTR,#imm targets (>=0x1000, likely data tables / XDATA):');
  [...dptrs.entries()].filter(([t]) => t >= 0x1000).sort((a, b) => a[0] - b[0]).forEach(([t, from]) =>
    console.log(`  0x${t.toString(16).padStart(4, '0')}  x${from.length}  first@0x${from[0].toString(16)}`));
}

if (opt.mode === 'tables') {
  // find MOVC/DMOV patterns preceded by a DPTR load
  let lastDptr = null;
  for (const ins of sweep()) {
    const d = ins.text.match(/^MOV DPTR,#0x([0-9a-f]+)$/);
    if (d) lastDptr = { v: parseInt(d[1], 16), at: ins.addr };
    if (ins.text.startsWith('MOVC A,@A+DPTR')) console.log(`  table base 0x${lastDptr ? lastDptr.v.toString(16) : '?'}  (dptr set @0x${lastDptr ? lastDptr.at.toString(16) : '?'}, movc @0x${ins.addr.toString(16)})`);
  }
}
