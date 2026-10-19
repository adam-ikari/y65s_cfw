# fetch-tools.ps1 — pull the third-party tools used by this project.
#
# Nothing here is vendored into git:
#   * tools/sinowisp  — ISP read/write tool (source, for auditing the protocol)
#   * tools/bin       — its official Windows release binary
#   * tools/smk       — open-source replacement firmware for Sinowealth 8051 keyboards
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\fetch-tools.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    # --- sinowisp source ---------------------------------------------------
    if (-not (Test-Path 'tools\sinowisp\.git')) {
        git clone --depth 1 https://github.com/karstx/sinowisp.git tools/sinowisp
    }

    # --- sinowisp Windows release (v2.1.0) ---------------------------------
    # sha256 of the archive: verify before trusting the binary.
    $bin = 'tools\bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    if (-not (Test-Path "$bin\sinowisp.exe")) {
        $url = 'https://github.com/karstx/sinowisp/releases/download/v2.1.0/sinowisp-win.tar.gz'
        $tar = "$bin\sinowisp-win.tar.gz"
        Invoke-WebRequest -Uri $url -OutFile $tar -UseBasicParsing
        tar -xzf $tar -C $bin
    }

    # --- SMK replacement firmware ------------------------------------------
    if (-not (Test-Path 'tools\smk\.git')) {
        git clone --depth 1 https://github.com/karstx/smk.git tools/smk
    }

    Write-Host 'tools ready.'
}
finally {
    Pop-Location
}
