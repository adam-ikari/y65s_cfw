# build-port.ps1 — sync the YD-Y65S port, configure SMK and compile the hex.
#
# Prerequisites (user scope):
#   scoop install sdcc meson ninja gcc
#   a real Python 3 (uv's managed interpreter is used if python3 is absent;
#   the Windows Store alias is a stub and does not count)
#   sinowisp on PATH or in tools/bin (only needed to define the flash target)
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\build-port.ps1
#         powershell -ExecutionPolicy Bypass -File tools\build-port.ps1 -Clean

param([switch]$Clean)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot 'sync-port.ps1')
& (Join-Path $PSScriptRoot 'patch-smk.ps1')

# scoop shims sdcc/meson/ninja, but not sdar/packihx from the sdcc package, and
# an interrupted gcc install can leave the package extracted without a shim.
$sdccBin = Join-Path $env:USERPROFILE 'scoop\apps\sdcc\current\bin'
if (Test-Path $sdccBin) {
    $env:PATH = "$sdccBin;$env:PATH"
}
$gccBin = Join-Path $env:USERPROFILE 'scoop\apps\gcc\current\bin'
if (Test-Path $gccBin) {
    $env:PATH = "$gccBin;$env:PATH"
}

# sinowisp is only needed to define the `flash` target.
$bin = Join-Path $root 'tools\bin'
if (Test-Path $bin) {
    $env:PATH = "$bin;$env:PATH"
}

# Meson requires a program literally named python3.  The Store alias is a stub,
# so fall back to uv's managed interpreter through a tiny shim.
$shimDir = Join-Path $root 'build\shim'
New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    $uvPy = (& uv python find 3.13.5 2>$null)
    if ($uvPy -and (Test-Path $uvPy)) {
        Set-Content -Path (Join-Path $shimDir 'python3.cmd') -Value "@`"$uvPy`" %*" -Encoding ascii
        $env:PATH = "$shimDir;$env:PATH"
    }
}

$buildDir = Join-Path $root 'build\smk-yd-y65s'
if ($Clean -and (Test-Path $buildDir)) {
    Remove-Item -Recurse -Force $buildDir
}

if (-not (Test-Path (Join-Path $buildDir 'build.ninja'))) {
    meson setup $buildDir (Join-Path $root 'tools\smk')
}

# Build only the YD-Y65S target.  Other boards in the SMK tree are third-party
# and may not compile with a newer SDCC; they are irrelevant to this port.
meson compile -C $buildDir yd-y65s_default_smk.hex

$hex = Join-Path $buildDir 'yd-y65s_default_smk.hex'
if (Test-Path $hex) {
    Write-Host "built $hex"
}
