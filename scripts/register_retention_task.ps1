<#
.SYNOPSIS
    Register the nightly GPS coordinate retention sweep in Windows Task Scheduler.

.DESCRIPTION
    Creates (or replaces) a scheduled task that runs

        powershell.exe -File scripts\run_retention_purge.ps1

    which in turn runs

        python -m app.scripts.retention_purge --confirm

    daily at 02:00. Section 5 of the biometric privacy policy requires raw
    coordinates to be deleted after 30 days; without a scheduled run that
    policy is a statement of intent with nothing enforcing it.

    The task action is the PowerShell wrapper rather than python.exe directly.
    Task Scheduler gives a task no console, so running python.exe as the action
    discards every log line and leaves only an exit code. Exit 1 means "at least
    one tenant raised", which is returned both when one known-stale tenant fails
    and when every tenant fails and retention is silently broken. The wrapper
    redirects the sweep's output to logs\retention\ so the two are
    distinguishable, and passes the exit code through unchanged.

    MUST BE RUN FROM AN ELEVATED POWERSHELL. Registering a task for a
    password-backed principal or for SYSTEM requires administrator rights.
    The script checks this first rather than failing with a raw HRESULT.

.PARAMETER RunAt
    Time of day to run, default 02:00 -- outside clock-in traffic and before
    any morning report.

.PARAMETER LogonType
    System        Runs as NT AUTHORITY\SYSTEM. No password prompt and runs
                  whether anyone is logged on. The application reads its
                  database credentials from the repo's configuration, not from
                  a user profile, so SYSTEM can reach the database.
    Password      Runs whether logged on or not. Windows prompts once for the
                  account password, which Task Scheduler stores. Requires the
                  account to have a password.
    Interactive   Runs only while the account is logged on. No password is
                  stored. Simplest, but a machine that is off or logged out at
                  02:00 misses the run entirely -- which for a retention
                  obligation is a silent failure.

.PARAMETER TaskName
    Task name, default "Payroll-RetentionPurge".

.EXAMPLE
    .\register_retention_task.ps1
    Registers for SYSTEM at 02:00. This is the default and the recommended
    choice on a server.

.EXAMPLE
    .\register_retention_task.ps1 -RunAt "03:30" -LogonType Password
    Registers for the current user at 03:30, with a stored password.

.NOTES
    Exit codes from the sweep, as recorded in Task Scheduler history and in
    logs\retention\:
        0   every tenant swept clean
        1   at least one tenant raised (check the log)
        2   purge completed but expired rows remain (holds or batch limit)
        99  the wrapper itself failed before or around the sweep

    Exit 1 and 2 both require attention. PowerShell surfaces Python's stderr
    logging as RemoteException -- the exit code is the signal, not the text.
#>
[CmdletBinding()]
param(
    [string]$RunAt = "02:00",
    [ValidateSet("System", "Password", "Interactive")]
    [string]$LogonType = "System",
    [string]$TaskName = "Payroll-RetentionPurge"
)

$ErrorActionPreference = "Stop"

# --- Elevation check -------------------------------------------------------
# Without this the caller gets "Access is denied / HRESULT 0x80070005" and has
# to guess what went wrong.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "ERROR: this script must run in an elevated PowerShell." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Right-click PowerShell -> 'Run as administrator', then:"
    Write-Host "    cd $((Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))"
    Write-Host "    .\scripts\register_retention_task.ps1 -LogonType $LogonType"
    exit 1
}

# --- Resolve paths from this script's location -----------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$WrapperScript = Join-Path $ScriptDir "run_retention_purge.ps1"

if (-not (Test-Path $PythonExe)) {
    Write-Host "ERROR: Python virtualenv not found at $PythonExe" -ForegroundColor Red
    exit 1
}

# The wrapper is what the task actually invokes, so a missing wrapper would
# register a task that fails every night. Check it now rather than at 02:00.
if (-not (Test-Path $WrapperScript)) {
    Write-Host "ERROR: wrapper script not found at $WrapperScript" -ForegroundColor Red
    Write-Host "  The scheduled task invokes this wrapper to capture the sweep's output." -ForegroundColor Red
    exit 1
}

Write-Host "Repository : $RepoRoot"
Write-Host "Python     : $PythonExe"
Write-Host "Wrapper    : $WrapperScript"
Write-Host "Schedule   : daily at $RunAt"
Write-Host "Logon type : $LogonType"
Write-Host "Task name  : $TaskName"
Write-Host ""

# The action is the wrapper, not python.exe -- see the .DESCRIPTION for why.
# -NoProfile keeps the run independent of whatever a user's profile script
# might do; -ExecutionPolicy Bypass is required because a Scheduled Task does
# not inherit an interactive session's execution policy.
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$WrapperScript`"" `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunAt

# StartWhenAvailable matters more than it looks: a machine asleep at 02:00
# would otherwise skip the run and retention would silently drift. The time
# limit bounds a runaway sweep; IgnoreNew stops tonight's run from overlapping
# a slow previous one.
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

switch ($LogonType) {
    "System" {
        $Principal = New-ScheduledTaskPrincipal `
            -UserId "NT AUTHORITY\SYSTEM" `
            -LogonType ServiceAccount `
            -RunLevel Highest
    }
    "Password" {
        $Principal = New-ScheduledTaskPrincipal `
            -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Password `
            -RunLevel Highest
    }
    "Interactive" {
        $Principal = New-ScheduledTaskPrincipal `
            -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive `
            -RunLevel Highest
    }
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Existing task found -- removing before re-registering."
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    } catch {
        Write-Host "ERROR: could not remove the existing task: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Registering task..."
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Deletes expired punch GPS coordinates (privacy policy section 5). Output in logs\retention\." `
        -ErrorAction Stop | Out-Null
} catch {
    Write-Host ""
    Write-Host "ERROR: task registration failed." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    if ($LogonType -eq "Password") {
        Write-Host "If this is an access error and you are elevated, the account may have"
        Write-Host "no password (Microsoft accounts often report one but reject it here)."
        Write-Host "Use -LogonType System instead, which needs no password."
    }
    exit 1
}

# --- Confirm it actually exists before claiming success --------------------
# Register-ScheduledTask has been observed to report no error while the task is
# absent. Claiming success on that basis is how a retention obligation quietly
# stops running.
$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $registered) {
    Write-Host "ERROR: Register-ScheduledTask reported no error but the task is absent." -ForegroundColor Red
    exit 1
}

Write-Host "Registered. State: $($registered.State)" -ForegroundColor Green
Write-Host ""
Write-Host "Verify:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Select-Object TaskName,State"
Write-Host ""
Write-Host "Trigger a run now:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Start-Sleep -Seconds 25"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$TaskName' | Select-Object LastTaskResult,LastRunTime"
Write-Host ""
Write-Host "Read what the sweep actually did (this is the real check):"
Write-Host "  Get-ChildItem logs\retention\"
Write-Host "  Get-Content (Get-ChildItem logs\retention\*.log | Sort-Object LastWriteTime | Select-Object -Last 1).FullName | Select-Object -Last 20"