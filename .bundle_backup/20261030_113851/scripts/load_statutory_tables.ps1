# Statutory table loader (control DB). F1: this is the only way to load
# statutory tables. No HTTP endpoints exist; platform_admin table absent.
#
# Examples:
#   .\scripts\load_statutory_tables.ps1 validate backend\tests\fixtures\fake_tax_tables\tax_bracket.json
#   .\scripts\load_statutory_tables.ps1 confirm  backend\tests\fixtures\fake_tax_tables\tax_bracket.json -TypedVersion "synthetic_fake_v1"
#   .\scripts\load_statutory_tables.ps1 end-date -TableId <uuid> -NewEndDate 2026-02-28
param(
    [Parameter(Mandatory=$true, Position=0)][ValidateSet("validate","confirm","end-date")][string]$Command,
    [Parameter(Position=1)][string]$File,
    [string]$TypedVersion,
    [string]$TableId,
    [string]$NewEndDate,
    [string]$Actor,
    [string]$DbUrl
)

$ErrorActionPreference = 'Stop'
$root = 'C:\xampp\htdocs\Payroll'
$backend = Join-Path $root 'backend'
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { $venvPython = 'python' }

Push-Location $backend
try {
    $argv = @('-m', 'app.services.statutory_loader', $Command)
    if ($Command -in @('validate','confirm')) {
        if (-not $File) { throw "STOP: $Command requires a File argument" }
        $argv += $File
    }
    if ($TypedVersion) { $argv += '--typed-version'; $argv += $TypedVersion }
    if ($TableId)      { $argv += '--table-id';       $argv += $TableId }
    if ($NewEndDate)   { $argv += '--new-end-date';   $argv += $NewEndDate }
    if ($Actor)        { $argv += '--actor';          $argv += $Actor }
    if ($DbUrl)        { $argv += '--db-url';         $argv += $DbUrl }
    & $venvPython @argv
    $rc = $LASTEXITCODE
    exit $rc
} finally { Pop-Location }

# END OF FILE
