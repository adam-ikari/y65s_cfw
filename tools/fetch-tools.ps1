# fetch-tools.ps1 — pull the third-party tools used by this project.
#
# Nothing here is vendored into git:
#   * tools/sinowisp  — ISP read/write tool (source, for auditing the protocol)
#   * tools/bin       — its official Windows release binary
#   * tools/smk       — open-source replacement firmware for Sinowealth 8051 keyboards
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\fetch-tools.ps1
#
# Some networks reset git-over-HTTPS to github.com while leaving the GitHub API
# reachable, so every clone falls back to the API tarball endpoint.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Get-GitHubTarball {
    param([string]$Repo, [string]$Ref, [string]$Dest)

    $tar = Join-Path $env:TEMP ((($Repo -replace '/', '-') + '-' + $Ref) + '.tar.gz')
    $url = "https://api.github.com/repos/$Repo/tarball/$Ref"
    Write-Host "downloading $Repo@$Ref ..."
    try {
        Invoke-WebRequest -Uri $url -OutFile $tar -UseBasicParsing -TimeoutSec 120
    }
    catch {
        curl.exe -sSL --retry 3 --max-time 180 -o $tar $url
        if ($LASTEXITCODE -ne 0) { throw "could not download $url" }
    }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    tar -xzf $tar -C $Dest --strip-components=1
    Remove-Item $tar
}

function Get-Repo {
    param([string]$Repo, [string]$Dest, [string]$Probe)

    if (Test-Path (Join-Path $Dest $Probe)) { return }
    try {
        git clone --depth 1 "https://github.com/$Repo.git" $Dest
    }
    catch {
        Write-Host "git clone failed, falling back to the API tarball"
        Get-GitHubTarball -Repo $Repo -Ref 'HEAD' -Dest $Dest
    }
}

Push-Location $root
try {
    # --- sinowisp source ---------------------------------------------------
    Get-Repo -Repo 'karstx/sinowisp' -Dest 'tools\sinowisp' -Probe 'Cargo.toml'

    # --- sinowisp Windows release (v2.1.0) ---------------------------------
    $bin = 'tools\bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    if (-not (Test-Path "$bin\sinowisp.exe")) {
        $url = 'https://github.com/karstx/sinowisp/releases/download/v2.1.0/sinowisp-x86_64-pc-windows-msvc-v2.1.0.tar.gz'
        $tar = "$bin\sinowisp.tar.gz"
        try {
            Invoke-WebRequest -Uri $url -OutFile $tar -UseBasicParsing -TimeoutSec 180
        }
        catch {
            curl.exe -sSL --retry 3 --max-time 180 -o $tar $url
            if ($LASTEXITCODE -ne 0) { throw "could not download $url" }
        }
        tar -xzf $tar -C $bin
        Remove-Item $tar
    }

    # --- SMK replacement firmware ------------------------------------------
    Get-Repo -Repo 'karstx/smk' -Dest 'tools\smk' -Probe 'meson.build'

    Write-Host 'tools ready.'
}
finally {
    Pop-Location
}
