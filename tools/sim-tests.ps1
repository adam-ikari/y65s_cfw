# sim-tests.ps1 — run the built firmware in SMK's patched uCsim, inside WSL.
#
# Prerequisites:
#   tools\fetch-tools.ps1   (SMK + sinowisp)
#   tools\build-port.ps1    (builds build/smk-yd-y65s/yd-y65s_default_smk.hex)
#   tools\build-ucsim.ps1   (builds the patched simulator)
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\sim-tests.ps1
#         powershell -ExecutionPolicy Bypass -File tools\sim-tests.ps1 `
#             -Ucsim /home/me/ucsim-build/sdcc-4.5.0/sim/ucsim/src/sims/s51.src/ucsim_51

param(
    [string]$Ucsim = '',       # WSL path; defaults to ~/ucsim-build/... in the script
    [string]$Firmware = ''     # WSL path; defaults to the repo build output
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required to run the simulator'
}

$script = (& wsl.exe -e wslpath -a (Join-Path $PSScriptRoot 'sim-tests.sh')).Trim()

$overrides = @()
if ($Ucsim) { $overrides += "SMK_UCSIM='$Ucsim'" }
if ($Firmware) { $overrides += "SMK_FIRMWARE='$Firmware'" }
$cmd = (@($overrides) + @("bash '$script'")) -join ' '

& wsl.exe -e bash -lc $cmd
if ($LASTEXITCODE -ne 0) {
    throw "simulation tests failed (exit $LASTEXITCODE)"
}
