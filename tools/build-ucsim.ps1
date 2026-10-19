# build-ucsim.ps1 — build SMK's patched uCsim (SH68F90 USB model) inside WSL.
#
# The simulator is a Linux binary, so it is built in WSL rather than on Windows.
# No root is needed: tools/build-ucsim.sh unpacks bison/flex into a private
# prefix. Requires WSL with gcc/g++/make/patch/curl (present in stock Ubuntu).
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\build-ucsim.ps1

$ErrorActionPreference = 'Stop'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required to build the simulator'
}

$script = Join-Path $PSScriptRoot 'build-ucsim.sh'
$wslScript = (& wsl.exe -e wslpath -a $script).Trim()

& wsl.exe -e bash $wslScript
if ($LASTEXITCODE -ne 0) {
    throw "ucsim build failed (exit $LASTEXITCODE)"
}
