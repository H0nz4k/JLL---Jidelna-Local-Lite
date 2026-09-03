[CmdletBinding()]
param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5433,
    [string]$UserName = "postgres",
    [string]$AdminDatabase = "postgres",
    [string]$TemplateDatabase = "",
    [string]$ExpectedSystemIdentifier = "",
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = "Stop"

# Konkrétní název LAB template databáze není v repozitáři; bere se z lokální
# konfigurace, jll_demo_lab je jen neutrální fallback.
if (-not $TemplateDatabase) {
    $ConfigPath = Join-Path $PSScriptRoot "..\config\lab.json"
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        $TemplateDatabase = (Get-Content -LiteralPath $ConfigPath -Raw |
            ConvertFrom-Json).database
    }
}
if (-not $TemplateDatabase) {
    $TemplateDatabase = "jll_demo_lab"
}

if ($HostName -notin @("localhost", "127.0.0.1", "::1")) {
    throw "LAB test runner odmítá non-local host '$HostName'."
}
if ($TemplateDatabase -notmatch '^jll_[a-zA-Z0-9_]+$') {
    throw "LAB template databáze musí začínat prefixem jll_."
}
if ($ExpectedSystemIdentifier -notmatch '^[0-9]+$') {
    throw "Vyžadován je ověřený -ExpectedSystemIdentifier lokálního clusteru."
}

$IdentitySql = @"
SELECT host(inet_server_addr())
    || '|' || inet_server_port()::text
    || '|' || EXISTS(
        SELECT 1 FROM pg_database WHERE datname = '$TemplateDatabase'
    )::text
    || '|' || (
        SELECT system_identifier::text FROM pg_control_system()
    );
"@
$Identity = & psql -X -w -h $HostName -p $Port -U $UserName -d $AdminDatabase -Atc $IdentitySql
if ($LASTEXITCODE -ne 0 -or -not $Identity) {
    throw "Lokální PostgreSQL instanci nelze bezpečně ověřit."
}
$Parts = $Identity.Trim().Split("|")
if (
    $Parts.Count -ne 4 -or
    $Parts[0] -notin @("127.0.0.1", "::1") -or
    [int]$Parts[1] -ne $Port -or
    $Parts[2] -ne "true" -or
    $Parts[3] -ne $ExpectedSystemIdentifier
) {
    throw "Server-side LAB guard nebo template databáze neprošly."
}

$env:JLL_LAB_ADMIN_DSN = "host=$HostName port=$Port user=$UserName dbname=$AdminDatabase"
$env:JLL_LAB_TEMPLATE = $TemplateDatabase
$env:JLL_LAB_SYSTEM_IDENTIFIER = $ExpectedSystemIdentifier

python -m pytest @PytestArgs
if ($LASTEXITCODE -ne 0) {
    throw "pytest skončil s exit code $LASTEXITCODE."
}
