<#
.SYNOPSIS
    Wrapper that runs the retention sweep and captures its output to a log.

.DESCRIPTION
    Task Scheduler gives a scheduled task no console. Running python.exe
    directly as the task action therefore discards every log line, leaving only
    an exit code -- and exit 1 means "at least one tenant raised", which is
    returned both when one known-stale tenant fails and when every tenant fails
    and retention is silently broken. The two are indistinguishable without the
    log.

    This wrapper runs the sweep, appends stdout and stderr to a dated log file
    under logs/retention/, and passes the sweep's exit code through unchanged so
    Task Scheduler's LastTaskResult still means what the runbook says it means.

    The exit code is captured explicitly rather than via $LASTEXITCODE after the
    redirect, because the redirect itself can fail and would otherwise mask the
    python result.

.NOTES
    Registered task action:
        powershell.exe -NoProfile -ExecutionPolicy Bypass
                       -File "...\scripts\run_retention_purge.ps1"
#>
$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

$LogDir = Join-Path $RepoRoot "logs\retention"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# One file per day. Long enough to review a week at a glance, short enough that
# a single file never grows without bound.
$Stamp = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "retention_$Stamp.log"

$Started = Get-Date
"===== run started $($Started.ToString('s')) =====" | Out-File -FilePath $LogFile -Append -Encoding utf8

Push-Location $RepoRoot
try {
    & $PythonExe -m app.scripts.retention_purge --confirm *>&1 |
        Out-File -FilePath $LogFile -Append -Encoding utf8
    $exit = $LASTEXITCODE
} catch {
    "WRAPPER ERROR: $($_.Exception.Message)" | Out-File -FilePath $LogFile -Append -Encoding utf8
    $exit = 99
} finally {
    Pop-Location
}

$Finished = Get-Date
$elapsed = [int]($Finished - $Started).TotalSeconds
"===== run finished exit=$exit elapsed=${elapsed}s =====" | Out-File -FilePath $LogFile -Append -Encoding utf8

exit $exit