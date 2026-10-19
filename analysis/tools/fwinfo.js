#!/usr/bin/env node
// fwinfo.js — basic structural analysis of an 8051 ISP image.
// Usage: node fwinfo.js <file.bin> [base-address-hex]
const fs = require('fs');

const file = process.argv[2];
if (!file) { console.error('usage: node fwinfo.js <file.bin> [base]'); process.exit(2); }
const base = process.argv[3] ? parseInt(process.argv[3], 16) : 0;
const b = fs.readFileSync(file);
const hex = (n, w = 5) => n.toString(16).toUpperCase().padStart(w, '0');

console.log(`file      : ${file}`);
console.log(`size      : ${b.length} bytes (0x${b.length.toString(16)})`);
console.log(`base      : 0x${base.toString(16)}`);

// --- byte histogram -------------------------------------------------
const hist = new Array(256).fill(0);
for (const x of b) hist[x]++;
const top = hist.map((c, v) => [v, c]).sort((a, z) => z[1] - a[1]).slice(0, 8);
console.log('top bytes : ' + top.map(([v, c]) => `${v.toString(16).padStart(2, '0')}x${c}(${(c / b.length * 100).toFixed(1)}%)`).join(' '));

// --- entropy per block ---------------------------------------------
const BLK = 1024;
const ent = (slice) => {
  const h = new Array(256).fill(0);
  for (const x of slice) h[x]++;
  let e = 0;
  for (const c of h) if (c) { const p = c / slice.length; e -= p * Math.log2(p); }
  return e;
};
console.log(`\nentropy per ${BLK}B block (bits/byte):`);
let line = '';
for (let off = 0; off < b.length; off += BLK) {
  const e = ent(b.subarray(off, Math.min(off + BLK, b.length)));
  line += `${hex(base + off, 4)} ${e.toFixed(2)}${(off / BLK) % 8 === 7 ? '\n' : '  '}`;
}
process.stdout.write(line.replace(/\n$/, '') + '\n');

// --- zero / 0xFF runs ----------------------------------------------
console.log('\nruns of >=64 identical bytes:');
let i = 0;
const runs = [];
while (i < b.length) {
  let j = i;
  while (j + 1 < b.length && b[j + 1] === b[i]) j++;
  if (j - i + 1 >= 64) runs.push([base + i, j - i + 1, b[i]]);
  i = j + 1;
}
if (!runs.length) console.log('  (none)');
for (const [a, len, v] of runs) console.log(`  ${hex(a, 4)}..${hex(a + len - 1, 4)}  ${String(len).padStart(6)} bytes of 0x${v.toString(16).padStart(2, '0')}`);

// --- ASCII strings --------------------------------------------------
console.log('\nascii strings (len>=4):');
const minLen = 4;
const out = [];
let s = -1;
for (let i = 0; i <= b.length; i++) {
  const c = i < b.length ? b[i] : 0;
  if (c >= 0x20 && c < 0x7f) { if (s < 0) s = i; continue; }
  if (s >= 0 && i - s >= minLen) out.push([base + s, b.subarray(s, i).toString('latin1')]);
  s = -1;
}
console.log(`  count: ${out.length}`);
for (const [a, str] of out) console.log(`  ${hex(a, 4)}  ${JSON.stringify(str)}`);

// --- vector table ---------------------------------------------------
console.log('\n8051 vectors (00/03/0B/13/1B/23/2B/33/3B/43/4B) and reset:');
const entries = [0x00, 0x03, 0x0b, 0x13, 0x1b, 0x23, 0x2b, 0x33, 0x3b, 0x43, 0x4b];
for (const e of entries) {
  const off = e - base;
  if (off < 0 || off + 3 > b.length) continue;
  const op = b[off], t = ((b[off + 1] << 8) | b[off + 2]);
  let desc = '';
  if (op === 0x02) desc = `LJMP  0x${t.toString(16)}`;
  else if (op === 0x00) desc = 'NOP (unused)';
  else if (op === 0x22) desc = 'RET';
  else desc = `first bytes: ${[...b.subarray(off, off + 4)].map(x => x.toString(16).padStart(2, '0')).join(' ')}`;
  console.log(`  ${hex(e, 4)}: ${desc}`);
}
