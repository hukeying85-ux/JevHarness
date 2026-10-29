#Requires -Version 5.1
<#
.SYNOPSIS
    One-command desktop base + 0fuye (arena/32cd826e-0fuye) + Arena Desk + LAN bridge installer.
    Pure ASCII for Windows PowerShell 5.1 compatibility.
#>
[CmdletBinding()]
param(
    [string]$ZeroFuyeUrl    = 'https://github.com/hukeying85-ux/0fuye.git',
    [string]$ZeroFuyeBranch = 'arena/32cd826e-0fuye',
    [string]$ZeroFuyePath   = 'C:\cgmd\0fuye',
    [string]$HubRoot        = 'C:\0github\.git-sync\desktop-base',
    [string]$Owner          = 'hukeying85-ux',
    [int]$IntervalSeconds   = 15,
    [switch]$SkipDeskWindow,
    [switch]$EnableLanBridge = $true
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

function Find-GitOnAnyDrive {
    foreach ($drv in @('C:\', 'D:\', 'E:\', 'F:\', 'G:\')) {
        if (-not (Test-Path -LiteralPath $drv)) { continue }
        foreach ($rel in @('Program Files\Git\cmd\git.exe', 'hermes\git\cmd\git.exe')) {
            $cand = Join-Path $drv $rel
            if (Test-Path -LiteralPath $cand) { return $cand }
        }
    }
    $cmd = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return 'git.exe'
}

$gitExe = Find-GitOnAnyDrive
New-Item -ItemType Directory -Force -Path $HubRoot, 'C:\0github\results', (Split-Path -Parent $ZeroFuyePath) | Out-Null

# 1. Clone or fast-forward hukeying85-ux/0fuye (arena/32cd826e-0fuye)
if (-not (Test-Path -LiteralPath (Join-Path $ZeroFuyePath '.git'))) {
    Write-Host "[1/5] Cloning $ZeroFuyeUrl ($ZeroFuyeBranch) -> $ZeroFuyePath"
    & $gitExe clone -b $ZeroFuyeBranch $ZeroFuyeUrl $ZeroFuyePath
} else {
    Write-Host "[1/5] Updating existing clone at $ZeroFuyePath ($ZeroFuyeBranch)"
    & $gitExe -C $ZeroFuyePath fetch origin $ZeroFuyeBranch
    & $gitExe -C $ZeroFuyePath checkout $ZeroFuyeBranch
    & $gitExe -C $ZeroFuyePath pull --ff-only origin $ZeroFuyeBranch
}

# 2. Bootstrap cgmd-hub if config/credentials do not exist yet
$cgBootstrap = Join-Path $ZeroFuyePath 'skills\cgmd-hub\bootstrap_desktop.ps1'
$cgCredFile  = Join-Path $ZeroFuyePath 'skills\cgmd-hub\state\git-credentials'
if (Test-Path -LiteralPath $cgBootstrap) {
    Write-Host "[2/5] Ensuring CGMD-Hub-Poll scheduled task and credentials..."
    if (Test-Path -LiteralPath $cgCredFile) {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $cgBootstrap -RepoPath $ZeroFuyePath -Branch $ZeroFuyeBranch -SkipCredentials -SkipWslSetup -SkipFirstPoll -NoBeaconTest -SkipSelfCheck
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cgBootstrap -RepoPath $ZeroFuyePath -Branch $ZeroFuyeBranch -SkipWslSetup -NoBeaconTest
    }
}

# 3. Compile zero-window GUI launcher ArenaSilentRun.exe and install repaired hub-watch.ps1
Write-Host "[3/5] Installing repaired zero-window git-sync-hub into $HubRoot..."
$csc = Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
$srCs = Join-Path $PSScriptRoot 'ArenaSilentRun.cs'
if (-not (Test-Path -LiteralPath $srCs)) {
    $srCs = Join-Path $ZeroFuyePath 'skills\git-sync-default\ArenaSilentRun.cs'
}
$srExe = Join-Path $HubRoot 'ArenaSilentRun.exe'
if ((Test-Path -LiteralPath $csc) -and (Test-Path -LiteralPath $srCs)) {
    try { Stop-ScheduledTask -TaskName 'git-sync-hub' -TaskPath '\' -ErrorAction SilentlyContinue } catch {}
    & $csc /nologo /target:winexe /optimize+ /out:$srExe $srCs | Out-Null
}

$hwSrc = Join-Path $PSScriptRoot 'hub-watch-desktop.ps1'
$hwDst = Join-Path $HubRoot 'hub-watch.ps1'
if (Test-Path -LiteralPath $hwSrc) {
    Copy-Item -LiteralPath $hwSrc -Destination $hwDst -Force
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $argStr = ('"{0}" -Owner {1} -BaseDirName desktop-base -Loop -IntervalSeconds {2}' -f $hwDst, $Owner, $IntervalSeconds)
    $act = if (Test-Path -LiteralPath $srExe) {
        New-ScheduledTaskAction -Execute $srExe -Argument $argStr -WorkingDirectory $HubRoot
    } else {
        New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File ' + $argStr) -WorkingDirectory $HubRoot
    }
    $trgLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
    $trgWatchdog = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
    $prin = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName 'git-sync-hub' -TaskPath '\' -Action $act -Trigger @($trgLogon, $trgWatchdog) -Principal $prin -Settings $set -Force | Out-Null
    Start-ScheduledTask -TaskName 'git-sync-hub' -TaskPath '\' -ErrorAction SilentlyContinue
}

# 4. Deploy Arena Desk v2.8 from 0fuye
$panelDeploy = Join-Path $ZeroFuyePath 'code\panel\deploy.ps1'
if (Test-Path -LiteralPath $panelDeploy) {
    Write-Host "[4/5] Deploying Arena Desk v2.8..."
    if ($SkipDeskWindow) {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $panelDeploy -NoOpenWindow -SkipAutoHeal | Out-Null
    } else {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $panelDeploy -OpenMainWindow -SkipAutoHeal | Out-Null
    }
}

# 5. Register optional zero-window LAN HTTP bridge (:8765) for millisecond calls
$bridgePs1 = Join-Path $ZeroFuyePath 'skills\cgmd-hub\runner\Invoke-CgmdBridge.ps1'
if ($EnableLanBridge -and (Test-Path -LiteralPath $bridgePs1)) {
    Write-Host "[5/5] Registering CGMD-LAN-Bridge (:8765)..."
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $bAct = if (Test-Path -LiteralPath $srExe) {
        New-ScheduledTaskAction -Execute $srExe -Argument ('"' + $bridgePs1 + '" -Loop') -WorkingDirectory (Split-Path -Parent $bridgePs1)
    } else {
        New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $bridgePs1 + '"') -WorkingDirectory (Split-Path -Parent $bridgePs1)
    }
    $bTrg = New-ScheduledTaskTrigger -AtLogOn -User $user
    $bPrin = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $bSet = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName 'CGMD-LAN-Bridge' -TaskPath '\' -Action $bAct -Trigger $bTrg -Principal $bPrin -Settings $bSet -Force | Out-Null
    Start-ScheduledTask -TaskName 'CGMD-LAN-Bridge' -TaskPath '\' -ErrorAction SilentlyContinue
}

$summary = [ordered]@{
    ok           = $true
    host         = $env:COMPUTERNAME
    hub_root     = $HubRoot
    zerofuye_dir = $ZeroFuyePath
    tasks        = @('git-sync-hub', 'CGMD-Hub-Poll', 'arena-desk-panel', 'CGMD-LAN-Bridge') | ForEach-Object {
        $t = Get-ScheduledTask -TaskName $_ -TaskPath '\' -ErrorAction SilentlyContinue
        [ordered]@{ name = $_; exists = ($null -ne $t); state = $(if ($t) { [string]$t.State } else { 'missing' }) }
    }
}
Write-Output ($summary | ConvertTo-Json -Depth 5)
