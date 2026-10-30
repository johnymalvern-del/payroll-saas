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
