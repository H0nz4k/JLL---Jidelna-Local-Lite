[CmdletBinding()]
param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5433,
    [string]$UserName = "postgres",
    [string]$AdminDatabase = "postgres",
    [string]$DatabaseName = "",
    [string]$ExpectedSystemIdentifier = "",
    [string]$DumpPath = "",
    [switch]$ConfirmFreshRestore
)

$ErrorActionPreference = "Stop"
$AllowedHosts = @("localhost", "127.0.0.1", "::1")

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable skončil s exit code $LASTEXITCODE."
    }
}

# Konkrétní název LAB databáze není v repozitáři; bere se z lokální
# konfigurace, jll_demo_lab je jen neutrální fallback.
if (-not $DatabaseName) {
    $ConfigPath = Join-Path $PSScriptRoot "..\config\lab.json"
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        $DatabaseName = (Get-Content -LiteralPath $ConfigPath -Raw |
            ConvertFrom-Json).database
    }
}
if (-not $DatabaseName) {
    $DatabaseName = "jll_demo_lab"
}

if ($HostName -notin $AllowedHosts) {
    throw "LAB restore odmítá non-local host '$HostName'."
}
if ($DatabaseName -notmatch '^jll_[a-zA-Z0-9_]+$') {
    throw "LAB databáze musí začínat prefixem jll_."
}
if ($ExpectedSystemIdentifier -notmatch '^[0-9]+$') {
    throw "Vyžadován je ověřený -ExpectedSystemIdentifier lokálního clusteru."
}
if (-not $ConfirmFreshRestore) {
    throw "Destruktivní fresh restore vyžaduje -ConfirmFreshRestore."
}

if (-not $DumpPath) {
    $DumpPath = Join-Path $PSScriptRoot "..\zdroje\demo.sql"
}
$ResolvedDump = (Resolve-Path -LiteralPath $DumpPath).Path
if (-not (Test-Path -LiteralPath $ResolvedDump -PathType Leaf)) {
    throw "Dump nebyl nalezen."
}

$IdentitySql = @"
SELECT current_database()
    || '|' || COALESCE(host(inet_server_addr()), '')
    || '|' || inet_server_port()::text
    || '|' || (
        SELECT system_identifier::text FROM pg_control_system()
    );
"@
$Identity = & psql -X -w -h $HostName -p $Port -U $UserName -d $AdminDatabase -Atc $IdentitySql
if ($LASTEXITCODE -ne 0 -or -not $Identity) {
    throw "Lokální PostgreSQL instanci nelze bezpečně ověřit."
}

$IdentityParts = $Identity.Trim().Split("|")
if ($IdentityParts.Count -ne 4) {
    throw "Server-side LAB identita má neočekávaný formát."
}
if ($IdentityParts[1] -notin @("127.0.0.1", "::1")) {
    throw "Server-side adresa '$($IdentityParts[1])' není loopback."
}
if ([int]$IdentityParts[2] -ne $Port) {
    throw "Server-side port neodpovídá požadovanému LAB portu."
}
if ($IdentityParts[3] -ne $ExpectedSystemIdentifier) {
    throw "PostgreSQL cluster neodpovídá schválenému lokálnímu LAB clusteru."
}

Write-Host "Ověřen lokální PostgreSQL $($IdentityParts[1]):$Port."
Write-Host "Fresh restore pouze databáze $DatabaseName."

$TerminateSql = @"
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$DatabaseName'
  AND pid <> pg_backend_pid();
"@
Invoke-Native "psql" @(
    "-X", "-w", "-h", $HostName, "-p", "$Port", "-U", $UserName,
    "-d", $AdminDatabase, "-v", "ON_ERROR_STOP=1", "-c", $TerminateSql
)
Invoke-Native "dropdb" @(
    "--if-exists", "-w", "-h", $HostName, "-p", "$Port", "-U", $UserName,
    $DatabaseName
)
Invoke-Native "createdb" @(
    "-w", "-h", $HostName, "-p", "$Port", "-U", $UserName,
    $DatabaseName
)
Invoke-Native "pg_restore" @(
    "--exit-on-error", "--no-owner", "--no-privileges",
    "-w", "-h", $HostName, "-p", "$Port", "-U", $UserName,
    "-d", $DatabaseName, $ResolvedDump
)

$VerifySql = @'
DO $jll$
BEGIN
    IF to_regprocedure(
        'public.objednavka_plus(integer,integer,integer,character,integer,text)'
    ) IS NULL THEN
        RAISE EXCEPTION 'Chybí public.objednavka_plus.';
    END IF;
    IF to_regprocedure(
        'public.objednavka_minus(integer,integer,integer,character,integer,text)'
    ) IS NULL THEN
        RAISE EXCEPTION 'Chybí public.objednavka_minus.';
    END IF;
    IF to_regprocedure(
        'public.insert_udalost(text,text,text,text,text,integer,text,integer,text)'
    ) IS NULL THEN
        RAISE EXCEPTION 'Chybí public.insert_udalost.';
    END IF;
END
$jll$;
SELECT current_database(), inet_server_addr(), inet_server_port();
'@
Invoke-Native "psql" @(
    "-X", "-w", "-h", $HostName, "-p", "$Port", "-U", $UserName,
    "-d", $DatabaseName, "-v", "ON_ERROR_STOP=1", "-c", $VerifySql
)

Write-Host "LAB restore dokončen: $DatabaseName"
