# sync-port.ps1 — copy the version-controlled YD-Y65S port into the SMK tree.
#
# The port lives under src/keyboards/yd-y65s/ in this repo (so it is reviewed
# and versioned); SMK itself is a throw-away checkout under tools/ and is
# gitignored.  Run this after editing the port, then build tools/smk.
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\sync-port.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root 'src\keyboards\yd-y65s'
$smk  = Join-Path $root 'tools\smk'
$dst  = Join-Path $smk 'src\keyboards\yd-y65s'

if (-not (Test-Path $smk)) {
    throw "SMK checkout missing at $smk - run tools\fetch-tools.ps1 first"
}

# Mirror (not merge) so a file deleted from the repo does not linger here.
if (Test-Path $dst) {
    Remove-Item -Recurse -Force $dst
}
Copy-Item -Recurse -Force $src $dst

$kbMeson = Join-Path $smk 'src\keyboards\meson.build'
$entry = "subdir('yd-y65s')"
if (-not (Select-String -Path $kbMeson -SimpleMatch $entry -Quiet)) {
    Add-Content -Path $kbMeson -Value $entry
}

Write-Host "synced $src -> $dst"
