#!/usr/bin/env bash
# build-ucsim.sh — build SMK's patched uCsim (the SH68F90 USB-interrupt model).
#
# SMK's flake builds this with Nix; this reproduces the same steps in a plain
# WSL userland and without root, by fetching bison/flex as .deb packages and
# unpacking them into a private prefix instead of installing them.
#
# Usage:  bash tools/build-ucsim.sh [workdir]      (default: ~/ucsim-build)
#         SDCC_VER=4.5.0 bash tools/build-ucsim.sh  (SDCC source version)
#
# Prints the path of the built simulator on success.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"
smk="$repo/tools/smk"
work="${1:-$HOME/ucsim-build}"
sdcc_ver="${SDCC_VER:-4.5.0}"

if [ ! -d "$smk/tools/ucsim" ]; then
    echo "SMK checkout missing at $smk — run tools/fetch-tools.ps1 first" >&2
    exit 1
fi

# flex/bison are not required here: they are unpacked into a private prefix below.
for tool in patch make gcc g++ curl tar dpkg-deb; do
    command -v "$tool" >/dev/null 2>&1 || { echo "missing host tool: $tool" >&2; exit 1; }
done

mkdir -p "$work/deps" "$work/root"

# --- flex/bison, no root: download the .deb files and unpack them privately --
if [ ! -x "$work/root/usr/bin/flex" ] || [ ! -x "$work/root/usr/bin/bison" ]; then
    (
        cd "$work/deps"
        rm -f ./*.deb
        apt-get download flex bison 2>/dev/null || apt-get download flex bison libfl2
        for d in ./*.deb; do dpkg-deb -x "$d" "$work/root"; done
    )
fi
export PATH="$work/root/usr/bin:$PATH"
export LD_LIBRARY_PATH="$work/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
# Bison hard-codes /usr/share/bison; point it at the unpacked copy.
export BISON_PKGDATADIR="$work/root/usr/share/bison"

# --- SDCC source (uCsim lives inside it) ------------------------------------
src="$work/sdcc-$sdcc_ver"
if [ ! -d "$src" ]; then
    echo "downloading SDCC $sdcc_ver source ..."
    curl -fsSL --retry 3 -o "$work/sdcc-src.tar.bz2" \
        "https://downloads.sourceforge.net/project/sdcc/sdcc/$sdcc_ver/sdcc-src-$sdcc_ver.tar.bz2"
    tar -xf "$work/sdcc-src.tar.bz2" -C "$work"
fi

# --- register the SH68F90 CPU + drop in its SIE model ------------------------
cd "$src"
if [ ! -f sim/ucsim/src/sims/s51.src/sh68f90.cc ]; then
    patch -p1 < "$smk/tools/ucsim/sh68f90-register.patch"
    cp "$smk/tools/ucsim/sh68f90.cc"  sim/ucsim/src/sims/s51.src/
    cp "$smk/tools/ucsim/sh68f90cl.h" sim/ucsim/src/sims/s51.src/
fi
# The tarball ships no generated lexer (see SMK's flake comment).
flex -o sim/ucsim/src/core/cmd.src/cmdlex.cc sim/ucsim/src/core/cmd.src/cmdlex.l

# --- build only the mcs51 simulator -----------------------------------------
cd sim/ucsim
if [ ! -f Makefile ]; then
    ./configure \
        --enable-avr-sim=no    --enable-f8-sim=no     --enable-i8048-sim=no \
        --enable-i8085-sim=no  --enable-m6800-sim=no  --enable-m6809-sim=no \
        --enable-m68hc08-sim=no --enable-m68hc11-sim=no --enable-m68hc12-sim=no \
        --enable-mos6502-sim=no --enable-oisc-sim=no  --enable-p1516-sim=no \
        --enable-pblaze-sim=no --enable-pdk-sim=no    --enable-rxk-sim=no \
        --enable-st7-sim=no    --enable-stm8-sim=no   --enable-tlcs-sim=no \
        --enable-xa-sim=no     --enable-z80-sim=no
fi
make -j"$(nproc)"

bin="$src/sim/ucsim/src/sims/s51.src/ucsim_51"
[ -x "$bin" ] || { echo "build produced no $bin" >&2; exit 1; }
echo "$bin"
