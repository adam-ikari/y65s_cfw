# patch-smk.ps1 — make the SMK checkout compile with SDCC 4.6.
#
# SDCC 4.6 added error 357 ("pointer to object in read-only code space should
# be pointer to const").  SMK's code-space reads use plain ``__code`` pointers,
# so the shared sources no longer compile once the compiler is upgraded.  The
# fix is the upstream-friendly one: mark those pointers const.
#
# The changes live in the throw-away tools/smk checkout, so this script is
# idempotent and re-applies them after every re-fetch.
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\patch-smk.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$smk = Join-Path $root 'tools\smk'

if (-not (Test-Path $smk)) {
    throw "SMK checkout missing at $smk - run tools\fetch-tools.ps1 first"
}

function Edit-File {
    param([string]$Path, [string]$Old, [string]$New)

    if (-not (Test-Path $Path)) { throw "missing $Path" }
    $text = Get-Content $Path -Raw
    if ($text.Contains($Old)) {
        Set-Content -Path $Path -Value ($text.Replace($Old, $New)) -Encoding utf8NoBOM
        Write-Host "patched $Path"
    }
}

# usb.c: APPEND() copies descriptor bytes out of code space.
Edit-File -Path (Join-Path $smk 'src\smk\usb.c') `
          -Old '((__code uint8_t *)(addr))' `
          -New '((const __code uint8_t *)(addr))'

# flash.c: the two MOVC window readers.
Edit-File -Path (Join-Path $smk 'src\sino51lib\flash.c') `
          -Old '(__code uint8_t *)(addr + i)' `
          -New '(const __code uint8_t *)(addr + i)'

Write-Host 'SMK compatibility patches applied.'
