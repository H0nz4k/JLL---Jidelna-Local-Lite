[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [switch]$ProbeOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ProjectRoot "config\lab.json"
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "LAB config neexistuje: $ConfigPath"
}
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Host "Chybí .venv. Spusťte:" -ForegroundColor Yellow
    Write-Host "  py -3.11 -m venv `"$ProjectRoot\.venv`""
    Write-Host "  & `"$ProjectRoot\.venv\Scripts\python.exe`" -m pip install -e `"${ProjectRoot}[test]`""
    exit 2
}

& $Python -c "import PySide6, psycopg, jll"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Chybí závislosti. Spusťte:" -ForegroundColor Yellow
    Write-Host "  & `"$Python`" -m pip install -e `"${ProjectRoot}[test]`""
    exit 3
}

& $Python -m jll.gui.probe $ConfigPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "LAB guard neprošel. GUI nebude spuštěno."
}
if ($ProbeOnly) {
    exit 0
}

Set-Location $ProjectRoot
& $Python -m jll --config $ConfigPath
exit $LASTEXITCODE
