#Requires -Version 5.1
<#
.SYNOPSIS
    git-sync-hub v4.5 (Desktop Repaired Edition) - Zero-Window Auto-Poll, Handshake & Sync Hub
    Pure ASCII for Windows PowerShell 5.1 compatibility.

.DESCRIPTION
    Repairs the 5 desktop-specific bugs discovered in 0fuye@arena/32cd826e-0fuye:
      1. Default $BaseDirName = 'desktop-base' + $PSScriptRoot protection so cycle #1
         cleanup never deletes C:\0github\.git-sync\desktop-base\hub-watch.ps1.
      2. Multi-drive tool discovery (C:..G:, including F:\Program Files\Git\cmd\git.exe
         and %LOCALAPPDATA%\Programs\Python\Python312\python.exe on DESKTOP-IEUDGS5).
      3. Credential bridge to C:\cgmd\0fuye\skills\cgmd-hub\state\git-credentials when
         global Git Credential Manager has no entry for hukeying85-ux.
      4. Active repository seed includes 0fuye and JevHarness; skips no-op receipt
         commits on 0fuye unless handshake.json or hub_task.json is pending.
      5. Works cleanly with ArenaSilentRun.exe -Loop without 60s premature exit.
#>
[CmdletBinding()]
param(
    [string]$Owner           = 'hukeying85-ux',
    [string]$SyncRoot        = 'C:\0github\.git-sync',
    [string]$ResultsRoot     = 'C:\0github\results',
    [string]$TopRoot         = 'C:\0github',
    [string]$BaseDirName     = 'desktop-base',
    [string]$CutoffIso       = '2026-10-20T00:00:00Z',
    [int]$IntervalSeconds    = 15,
    [switch]$Loop,
    [switch]$Status
)

$ErrorActionPreference = 'Continue'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE     = 'never'

try {
    if (-not ('Win32.ConsoleHide' -as [type])) {
        Add-Type -Namespace Win32 -Name ConsoleHide -MemberDefinition '
            [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
            [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        ' -ErrorAction SilentlyContinue
    }
    $hwnd = [Win32.ConsoleHide]::GetConsoleWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        [void][Win32.ConsoleHide]::ShowWindow($hwnd, 0)
    }
} catch {}

$TaskName  = 'git-sync-hub'
$StateRoot = Join-Path $env:USERPROFILE '.git-sync-hub'
if (-not (Test-Path -LiteralPath $StateRoot)) {
    New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
}
$LogFile       = Join-Path $StateRoot 'hub-watch.log'
$StateJson     = Join-Path $StateRoot 'hub-state.json'
$SeenHeadsJson = Join-Path $StateRoot 'seen-heads.json'
$PidFile       = Join-Path $StateRoot 'hub-watch.pid'

$DriveRoots = @('C:\', 'D:\', 'E:\', 'F:\', 'G:\') | Where-Object { Test-Path -LiteralPath $_ }

function Write-HubLog([string]$Msg) {
    $line = "[{0}] [pid={1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID, $Msg
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

function Find-GitExe {
    foreach ($drv in $DriveRoots) {
        foreach ($rel in @('Program Files\Git\cmd\git.exe', 'Program Files\Git\bin\git.exe', 'hermes\git\cmd\git.exe', 'hermes\git\bin\git.exe')) {
            $c = Join-Path $drv $rel
            if (Test-Path -LiteralPath $c) { return $c }
        }
    }
    $cmd = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return 'git.exe'
}

function Find-BashExe {
    foreach ($drv in $DriveRoots) {
        foreach ($rel in @('Program Files\Git\bin\bash.exe', 'hermes\git\bin\bash.exe', 'hermes\git\usr\bin\bash.exe')) {
            $c = Join-Path $drv $rel
            if (Test-Path -LiteralPath $c) { return $c }
        }
    }
    $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return 'bash.exe'
}

function Find-PythonExe {
    if ($env:LOCALAPPDATA) {
        $pyDirs = @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*') -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
        foreach ($pd in $pyDirs) {
            $py = Join-Path $pd.FullName 'python.exe'
            if (Test-Path -LiteralPath $py) { return $py }
        }
    }
    foreach ($drv in $DriveRoots) {
        foreach ($rel in @('Python312\python.exe', 'Python311\python.exe', 'Miniforge3\python.exe', 'miniconda3\python.exe', 'spider\python.exe')) {
            $c = Join-Path $drv $rel
            if (Test-Path -LiteralPath $c) { return $c }
        }
    }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return 'python.exe'
}

function Find-CgmdCredentialFile {
    foreach ($drv in $DriveRoots) {
        $cand = Join-Path $drv 'cgmd\0fuye\skills\cgmd-hub\state\git-credentials'
        if (Test-Path -LiteralPath $cand) { return ($cand -replace '\\', '/') }
    }
    return ''
}

$GitExe       = Find-GitExe
$BashExe      = Find-BashExe
$PythonExe    = Find-PythonExe
$CgmdCredFile = Find-CgmdCredentialFile

function Invoke-ProcessSilent {
    param(
        [string]$FileName,
        [string]$Arguments,
        [string]$WorkingDirectory = $PSScriptRoot,
        [int]$TimeoutSeconds = 120,
        [string]$StdinText = ''
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName               = $FileName
        $psi.Arguments              = $Arguments
        if ($WorkingDirectory -and (Test-Path -LiteralPath $WorkingDirectory)) {
            $psi.WorkingDirectory   = $WorkingDirectory
        }
        $psi.UseShellExecute        = $false
        $psi.CreateNoWindow         = $true
        $psi.WindowStyle            = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError  = $true
        $psi.RedirectStandardInput  = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding  = [System.Text.Encoding]::UTF8

        $proc = [System.Diagnostics.Process]::Start($psi)
        if ($StdinText) {
            $proc.StandardInput.Write($StdinText)
        }
        try { $proc.StandardInput.Close() } catch {}
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()

        $finished = $proc.WaitForExit($TimeoutSeconds * 1000)
        if (-not $finished) {
            try { & taskkill.exe /F /T /PID $proc.Id >$null 2>&1 } catch {}
            try { $proc.Kill() } catch {}
            try { [void]$proc.WaitForExit(2000) } catch {}
        }
        $sw.Stop()
        $outStr = ''
        $errStr = ''
        try { if ($outTask.Wait(2000)) { $outStr = [string]$outTask.Result } } catch {}
        try { if ($errTask.Wait(2000)) { $errStr = [string]$errTask.Result } } catch {}
        return @{
            exit_code  = if ($finished) { [int]$proc.ExitCode } else { 124 }
            stdout     = $outStr
            stderr     = $errStr
            elapsed_ms = [int]$sw.ElapsedMilliseconds
            timed_out  = (-not $finished)
        }
    } catch {
        $sw.Stop()
        return @{
            exit_code  = 1
            stdout     = ''
            stderr     = $_.Exception.Message
            elapsed_ms = [int]$sw.ElapsedMilliseconds
            timed_out  = $false
        }
    }
}

function Invoke-GitSilent {
    param(
        [string]$Arguments,
        [string]$WorkingDirectory = $PSScriptRoot,
        [int]$TimeoutSeconds = 30,
        [switch]$WithOwnerCreds
    )
    $credArg = ''
    if ($WithOwnerCreds -and $CgmdCredFile) {
        $credArg = "-c `"credential.helper=store --file=$CgmdCredFile`" "
    }
    return Invoke-ProcessSilent -FileName $GitExe -Arguments "-c core.fsmonitor=false -c gc.auto=0 -c maintenance.auto=false -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=20 $credArg$Arguments" -WorkingDirectory $WorkingDirectory -TimeoutSeconds $TimeoutSeconds
}

function Get-GitHubToken {
    if ($script:CachedGhToken) { return $script:CachedGhToken }
    try {
        $res = Invoke-ProcessSilent -FileName $GitExe -Arguments 'credential fill' -StdinText "protocol=https`nhost=github.com`nusername=$Owner`n`n" -TimeoutSeconds 10
        foreach ($line in ($res.stdout -split "`r?`n")) {
            if ($line -match '^password=(.+)$') {
                $script:CachedGhToken = $Matches[1].Trim()
                return $script:CachedGhToken
            }
        }
    } catch {}
    if ($CgmdCredFile -and (Test-Path -LiteralPath ($CgmdCredFile -replace '/', '\'))) {
        try {
            $lines = [System.IO.File]::ReadAllLines(($CgmdCredFile -replace '/', '\'), [System.Text.Encoding]::UTF8)
            foreach ($ln in $lines) {
                if ($ln -match '^https://([^:@/]+):([^@/]+)@github\.com') {
                    $u = [Uri]::UnescapeDataString($Matches[1])
                    $p = [Uri]::UnescapeDataString($Matches[2])
                    if ((-not $Owner) -or ($u -ieq $Owner)) {
                        $script:CachedGhToken = $p.Trim()
                        return $script:CachedGhToken
                    }
                }
            }
        } catch {}
    }
    return ''
}

function Get-ShortCloneName([string]$RepoName, [string]$Branch) {
    $slug = $Branch -replace '^arena/', ''
    return "{0}-{1}" -f $RepoName, $slug
}

function Remove-TreeSafe([string]$Target) {
    if (-not (Test-Path -LiteralPath $Target)) { return $true }
    try {
        & cmd.exe /c "attrib -r -s -h `"$Target\*`" /s /d >nul 2>&1"
        & cmd.exe /c "rmdir /s /q `"$Target`" >nul 2>&1"
        if (Test-Path -LiteralPath $Target) {
            Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    return (-not (Test-Path -LiteralPath $Target))
}

function Write-LocalFileSafe([string]$TargetPath, [byte[]]$Bytes, [string]$TextContent, [bool]$UseBytes = $false) {
    $writtenPaths = @()
    $zhDesktop = "$([char]0x684C)$([char]0x9762)"
    $candidates = @($TargetPath)

    $realDesktop = [Environment]::GetFolderPath('Desktop')
    if ($realDesktop -and ($TargetPath -match [regex]::Escape($zhDesktop) -or $TargetPath -match '(?i)\\Desktop\\')) {
        $leaf = Split-Path -Path $TargetPath -Leaf
        $altDesktopPath = Join-Path $realDesktop $leaf
        if ($candidates -notcontains $altDesktopPath) {
            $candidates += $altDesktopPath
        }
    }

    foreach ($cand in $candidates) {
        try {
            $parent = Split-Path -Path $cand -Parent
            if ($parent -and (-not (Test-Path -LiteralPath $parent))) {
                New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop | Out-Null
            }
            if ($UseBytes) {
                [System.IO.File]::WriteAllBytes($cand, $Bytes)
            } else {
                [System.IO.File]::WriteAllText($cand, $TextContent, (New-Object System.Text.UTF8Encoding($false)))
            }
            if (Test-Path -LiteralPath $cand) {
                $writtenPaths += $cand
            }
        } catch {}
    }
    return $writtenPaths
}

function Copy-ResultsFromDir([string]$SourceDir, [string]$ShortName) {
    if (-not (Test-Path -LiteralPath $SourceDir)) { return $false }
    $copiedAny = $false
    foreach ($sub in @('results', 'deliverable')) {
        $src = Join-Path $SourceDir $sub
        if (Test-Path -LiteralPath $src) {
            $items = @(Get-ChildItem -LiteralPath $src -Force -ErrorAction SilentlyContinue)
            if ($items.Count -gt 0) {
                $dst = if ($sub -eq 'results') { Join-Path $ResultsRoot $ShortName } else { Join-Path (Join-Path $ResultsRoot $ShortName) 'deliverable' }
                if (-not (Test-Path -LiteralPath $dst)) {
                    New-Item -ItemType Directory -Path $dst -Force | Out-Null
                }
                & robocopy.exe $src $dst /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
                $copiedAny = $true
            }
        }
    }
    return $copiedAny
}

function Get-SeenHeads {
    $map = @{}
    if (Test-Path -LiteralPath $SeenHeadsJson) {
        try {
            $curObj = Get-Content -LiteralPath $SeenHeadsJson -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $curObj.PSObject.Properties) {
                $map[[string]$p.Name] = [string]$p.Value
            }
        } catch {}
    }
    return $map
}

function Save-SeenHeads([hashtable]$Map) {
    try {
        $clean = [ordered]@{}
        foreach ($k in ($Map.Keys | Sort-Object)) {
            $clean[[string]$k] = [string]$Map[$k]
        }
        ($clean | ConvertTo-Json -Depth 3) | Set-Content -LiteralPath $SeenHeadsJson -Encoding UTF8
    } catch {}
}

function Invoke-ResultsOnlyCleanup {
    if (-not (Test-Path -LiteralPath $ResultsRoot)) {
        New-Item -ItemType Directory -Path $ResultsRoot -Force | Out-Null
    }
    $protectedNames = @($BaseDirName, 'desktop-base', 'leanrea-626378d6-leanrea')
    $selfFull = ''
    try { $selfFull = (Resolve-Path -LiteralPath $PSScriptRoot).Path.TrimEnd('\') } catch { $selfFull = $PSScriptRoot }

    $evictedClones = 0
    if (Test-Path -LiteralPath $SyncRoot) {
        $dirs = @(Get-ChildItem -LiteralPath $SyncRoot -Directory -Force -ErrorAction SilentlyContinue)
        foreach ($d in $dirs) {
            if ($protectedNames -icontains $d.Name) { continue }
            if ($selfFull -and ($d.FullName.TrimEnd('\') -ieq $selfFull)) { continue }
            Copy-ResultsFromDir -SourceDir $d.FullName -ShortName $d.Name | Out-Null
            if (Remove-TreeSafe -Target $d.FullName) {
                $evictedClones++
            }
        }
    }
    return @{ evicted_clones = $evictedClones; evicted_top = 0 }
}

function Test-BranchHasPendingWork([string]$ProjectDir, [string]$RepoName) {
    $hsPath = Join-Path $ProjectDir 'results\status\handshake.json'
    if (Test-Path -LiteralPath $hsPath) {
        try {
            $hs = Get-Content -LiteralPath $hsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($hs.local_state -eq 'pending') { return $true }
        } catch {}
    }
    foreach ($rel in @('results\status\hub_task.json', 'results\task\task.json', 'results\status\desktop_target.json')) {
        $p = Join-Path $ProjectDir $rel
        if (Test-Path -LiteralPath $p) {
            try {
                $j = Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
                if (($j.status -ne 'completed_on_host') -and ($j.status -ne 'confirmed_written_on_host')) { return $true }
            } catch {}
        }
    }
    # 0fuye already has CGMD-Hub-Poll every 60s; avoid pushing empty sync receipts onto 0fuye
    if ($RepoName -ieq '0fuye') { return $false }
    return $true
}

function Invoke-BranchTasksSilently([string]$ProjectDir, [string]$RepoName, [string]$Branch, [string]$ShortName, [string]$SourceSha) {
    $execLogs = @()
    $copiedTargets = @()
    $env:HUB_REPO_DIR    = $ProjectDir
    $env:HUB_RESULTS_DIR = (Join-Path $ResultsRoot $ShortName)
    $env:HUB_PYTHON_EXE  = $PythonExe

    foreach ($taskJsonRel in @('results\status\hub_task.json', 'results\task\task.json')) {
        $tjPath = Join-Path $ProjectDir $taskJsonRel
        if (-not (Test-Path -LiteralPath $tjPath)) { continue }
        try {
            $tj = Get-Content -LiteralPath $tjPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($tj.PSObject.Properties['enabled'] -and ($tj.enabled -eq $false)) { continue }
            if (($tj.status -eq 'completed_on_host') -and (-not $tj.always_run)) { continue }
            $taskFailed = $false
            $taskWritten = @()

            if ($tj.write_files) {
                foreach ($wf in @($tj.write_files)) {
                    if (-not $wf.path) { continue }
                    $wPaths = @(Write-LocalFileSafe -TargetPath ([string]$wf.path) -TextContent ([string]$wf.content) -UseBytes $false)
                    $copiedTargets += $wPaths
                    $taskWritten += $wPaths
                    if ($wPaths.Count -eq 0) { $taskFailed = $true }
                    $execLogs += [ordered]@{ step = "write_file: $($wf.path)"; exit_code = $(if ($wPaths.Count -gt 0) { 0 } else { 1 }); written_to = $wPaths }
                }
            }
            if ($tj.copy_files) {
                foreach ($cf in @($tj.copy_files)) {
                    $srcRel = ([string]$cf.source) -replace '/', '\'
                    $tgt    = [string]($cf.target, $cf.target_path | Where-Object { $_ } | Select-Object -First 1)
                    $srcFull = Join-Path $ProjectDir $srcRel
                    if ($tgt -and (Test-Path -LiteralPath $srcFull)) {
                        $b = [System.IO.File]::ReadAllBytes($srcFull)
                        $wPaths = @(Write-LocalFileSafe -TargetPath $tgt -Bytes $b -UseBytes $true)
                        $copiedTargets += $wPaths
                        $taskWritten += $wPaths
                        if ($wPaths.Count -eq 0) { $taskFailed = $true }
                        $execLogs += [ordered]@{ step = "copy_file: $srcRel -> $tgt"; exit_code = $(if ($wPaths.Count -gt 0) { 0 } else { 1 }); written_to = $wPaths; bytes = $b.Length }
                    }
                }
            }
            if ($tj.powershell) {
                foreach ($psCmd in @($tj.powershell)) {
                    if (-not $psCmd) { continue }
                    $tmpPs = Join-Path $env:TEMP ("hub_inline_{0}.ps1" -f [guid]::NewGuid().ToString('N'))
                    [System.IO.File]::WriteAllText($tmpPs, [string]$psCmd, (New-Object System.Text.UTF8Encoding($true)))
                    $r = Invoke-ProcessSilent -FileName 'powershell.exe' -Arguments "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$tmpPs`"" -WorkingDirectory $ProjectDir -TimeoutSeconds 180
                    Remove-Item -LiteralPath $tmpPs -Force -ErrorAction SilentlyContinue
                    if ($r.exit_code -ne 0) { $taskFailed = $true }
                    $execLogs += [ordered]@{ step = 'hub_task.powershell'; exit_code = $r.exit_code; elapsed_ms = $r.elapsed_ms; stdout = $r.stdout.Trim(); stderr = $r.stderr.Trim() }
                }
            }
            if ($tj.python) {
                foreach ($pyCmd in @($tj.python)) {
                    if (-not $pyCmd) { continue }
                    $tmpPy = Join-Path $env:TEMP ("hub_inline_{0}.py" -f [guid]::NewGuid().ToString('N'))
                    [System.IO.File]::WriteAllText($tmpPy, [string]$pyCmd, (New-Object System.Text.UTF8Encoding($false)))
                    $r = Invoke-ProcessSilent -FileName $PythonExe -Arguments "`"$tmpPy`"" -WorkingDirectory $ProjectDir -TimeoutSeconds 180
                    Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
                    if ($r.exit_code -ne 0) { $taskFailed = $true }
                    $execLogs += [ordered]@{ step = 'hub_task.python'; exit_code = $r.exit_code; elapsed_ms = $r.elapsed_ms; stdout = $r.stdout.Trim(); stderr = $r.stderr.Trim() }
                }
            }
            if ($tj.bash) {
                foreach ($shCmd in @($tj.bash)) {
                    if (-not $shCmd) { continue }
                    $tmpSh = Join-Path $env:TEMP ("hub_inline_{0}.sh" -f [guid]::NewGuid().ToString('N'))
                    [System.IO.File]::WriteAllText($tmpSh, (([string]$shCmd) -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
                    $r = Invoke-ProcessSilent -FileName $BashExe -Arguments "`"$tmpSh`"" -WorkingDirectory $ProjectDir -TimeoutSeconds 180
                    Remove-Item -LiteralPath $tmpSh -Force -ErrorAction SilentlyContinue
                    if ($r.exit_code -ne 0) { $taskFailed = $true }
                    $execLogs += [ordered]@{ step = 'hub_task.bash'; exit_code = $r.exit_code; elapsed_ms = $r.elapsed_ms; stdout = $r.stdout.Trim(); stderr = $r.stderr.Trim() }
                }
            }

            $tj | Add-Member -NotePropertyName 'status' -NotePropertyValue ($(if ($taskFailed) { 'failed_on_host' } else { 'completed_on_host' })) -Force
            $tj | Add-Member -NotePropertyName 'executed_on_host' -NotePropertyValue $env:COMPUTERNAME -Force
            $tj | Add-Member -NotePropertyName 'executed_at_utc' -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')) -Force
            $tj | Add-Member -NotePropertyName 'source_commit' -NotePropertyValue $SourceSha -Force
            if ($taskWritten.Count -gt 0) {
                $tj | Add-Member -NotePropertyName 'written_paths' -NotePropertyValue $taskWritten -Force
            }
            ($tj | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $tjPath -Encoding UTF8
        } catch {
            $execLogs += [ordered]@{ step = $taskJsonRel; exit_code = 1; error = $_.Exception.Message }
        }
    }

    return @{ exec_logs = $execLogs; copied_targets = $copiedTargets }
}

function Push-ResultsReceipt([string]$ProjectDir, [string]$RepoName, [string]$Branch, [string]$ShortName, [string]$SourceSha, [hashtable]$TaskOutcome) {
    $statusDir = Join-Path $ProjectDir 'results\status'
    if (-not (Test-Path -LiteralPath $statusDir)) {
        New-Item -ItemType Directory -Path $statusDir -Force | Out-Null
    }
    $execLogs = @($TaskOutcome.exec_logs)
    $copiedTargets = @($TaskOutcome.copied_targets)
    $allOk = $true
    foreach ($el in $execLogs) {
        if ($el.exit_code -ne 0) { $allOk = $false }
    }

    if ($execLogs.Count -gt 0) {
        $lines = @(
            "== git-sync-hub v4.5 execution log on $env:COMPUTERNAME ==",
            "repo: $RepoName",
            "branch: $Branch",
            "source_commit: $SourceSha",
            "executed_at_utc: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))",
            "tasks_all_ok: $allOk",
            ""
        )
        foreach ($el in $execLogs) {
            $lines += "--- step: $($el.step) (exit=$($el.exit_code)) ---"
            if ($el.stdout) { $lines += $el.stdout }
            if ($el.stderr) { $lines += "[stderr] $($el.stderr)" }
            if ($el.error)  { $lines += "[error] $($el.error)" }
            $lines += ""
        }
        Set-Content -LiteralPath (Join-Path $statusDir 'hub_exec_output.txt') -Value ($lines -join "`r`n") -Encoding UTF8
    }

    Copy-ResultsFromDir -SourceDir $ProjectDir -ShortName $ShortName | Out-Null
    $localResDir = Join-Path $ResultsRoot $ShortName
    if (-not (Test-Path -LiteralPath $localResDir)) {
        New-Item -ItemType Directory -Path $localResDir -Force | Out-Null
    }
    $fileCount = @(Get-ChildItem -LiteralPath $localResDir -Recurse -File -Force -ErrorAction SilentlyContinue).Count
    $nowUtc    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $nowLocal  = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')

    $receipt = [ordered]@{
        status               = 'synced'
        host                 = $env:COMPUTERNAME
        repo                 = $RepoName
        branch               = $Branch
        source_commit        = $SourceSha
        synced_at_utc        = $nowUtc
        synced_at_local      = $nowLocal
        poll_interval_sec    = $IntervalSeconds
        local_results_dir    = $localResDir
        synced_files_count   = $fileCount
        tasks_executed_count = $execLogs.Count
        tasks_all_ok         = $allOk
        tasks_executed       = $execLogs
        copied_targets       = $copiedTargets
        mode                 = 'auto-poll-exec-and-sync-zero-window-v4.5'
    }
    ($receipt | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath (Join-Path $statusDir 'hub_sync_receipt.json') -Encoding UTF8

    $hsPath = Join-Path $statusDir 'handshake.json'
    if (Test-Path -LiteralPath $hsPath) {
        try {
            $hs = Get-Content -LiteralPath $hsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($hs.local_state -eq 'pending') {
                $verdict = if ($allOk) { 'passed' } else { 'failed' }
                $hs | Add-Member -NotePropertyName 'local_state' -NotePropertyValue $verdict -Force
                $hs | Add-Member -NotePropertyName 'local_updated' -NotePropertyValue $nowLocal -Force
                $hs | Add-Member -NotePropertyName 'host' -NotePropertyValue $env:COMPUTERNAME -Force
                ($hs | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath $hsPath -Encoding UTF8
            }
        } catch {}
    }

    Copy-ResultsFromDir -SourceDir $ProjectDir -ShortName $ShortName | Out-Null

    try {
        [void](Invoke-GitSilent -Arguments "-C `"$ProjectDir`" config user.name `"git-sync-hub ($env:COMPUTERNAME)`"" -WorkingDirectory $ProjectDir -TimeoutSeconds 10)
        [void](Invoke-GitSilent -Arguments "-C `"$ProjectDir`" config user.email `"$Owner@users.noreply.github.com`"" -WorkingDirectory $ProjectDir -TimeoutSeconds 10)
        if (Test-Path -LiteralPath (Join-Path $ProjectDir 'results')) {
            [void](Invoke-GitSilent -Arguments "-C `"$ProjectDir`" add -A results" -WorkingDirectory $ProjectDir -TimeoutSeconds 20)
        }
        if (Test-Path -LiteralPath (Join-Path $ProjectDir 'deliverable')) {
            [void](Invoke-GitSilent -Arguments "-C `"$ProjectDir`" add -A deliverable" -WorkingDirectory $ProjectDir -TimeoutSeconds 20)
        }
        [void](Invoke-GitSilent -Arguments "-C `"$ProjectDir`" commit -m `"hub($env:COMPUTERNAME): exec & sync to $localResDir`" --quiet" -WorkingDirectory $ProjectDir -TimeoutSeconds 20)
        $pushRes = Invoke-GitSilent -Arguments "-C `"$ProjectDir`" push origin $Branch --quiet" -WorkingDirectory $ProjectDir -TimeoutSeconds 45 -WithOwnerCreds
        if ($pushRes.exit_code -ne 0) {
            Write-HubLog ("WARN: push exit={0} on {1}: {2}" -f $pushRes.exit_code, $ShortName, $pushRes.stderr.Trim())
        }
    } catch {
        Write-HubLog "WARN: receipt push failed on ${ShortName}: $($_.Exception.Message)"
    }
}

function Get-TargetReposToCheck {
    $skipRepos = @('git-pull-arena', 'rea', 'Light-skills', 'subs-check-pro', 'AgentArena', 'BrowserSkill', 'zhongqi')
    $seedRepos = @('0fuye', 'JevHarness', 'skills', 'mu', 'jev-chat-jarvis')
    if ((-not $script:ActiveRepoNames) -or ($script:ActiveRepoNames.Count -gt 16)) {
        $script:ActiveRepoNames = $seedRepos
    } else {
        $script:ActiveRepoNames = @($script:ActiveRepoNames | Where-Object { $_ -notin $skipRepos })
    }
    $now = Get-Date
    if ((-not $script:LastApiRefresh) -or (($now - $script:LastApiRefresh).TotalSeconds -ge 45)) {
        $script:LastApiRefresh = $now
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $headers = @{
            'User-Agent' = 'jevharness-desktop-base/4.5'
            'Accept'     = 'application/vnd.github.v3+json'
        }
        $tok = Get-GitHubToken
        if ($tok) {
            $headers['Authorization'] = "Bearer $tok"
        }
        $url = if ($tok) {
            'https://api.github.com/user/repos?affiliation=owner&per_page=20&sort=pushed&direction=desc'
        } else {
            "https://api.github.com/users/$Owner/repos?per_page=20&sort=pushed&direction=desc"
        }
        try {
            $repos = Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 15 -ErrorAction Stop
            $fresh = @() + $seedRepos
            foreach ($r in $repos) {
                if (-not $r.pushed_at) { continue }
                $rn = [string]$r.name
                if ($rn -in $skipRepos) { continue }
                $pushedIso = ([DateTime]$r.pushed_at).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
                if ($pushedIso -ge $CutoffIso) {
                    if ($fresh -notcontains $rn) { $fresh += $rn }
                }
            }
            $script:ActiveRepoNames = @($fresh | Select-Object -First 16)
        } catch {
            Write-HubLog "WARN: API refresh skipped (using seed list): $($_.Exception.Message)"
        }
    }
    return $script:ActiveRepoNames
}

function Sync-NewRemoteBranches {
    $seen    = Get-SeenHeads
    $changed = $false
    $synced  = 0

    $tempRoot = Join-Path $env:TEMP 'git-sync-hub-ephemeral'
    if (-not (Test-Path -LiteralPath $tempRoot)) {
        New-Item -ItemType Directory -Path $tempRoot -Force -ErrorAction SilentlyContinue | Out-Null
    }

    $repoNames = @(Get-TargetReposToCheck)
    foreach ($repoName in $repoNames) {
        if ($synced -ge 3) { break }
        $cloneUrl = "https://github.com/$Owner/$repoName.git"
        $lsRes = Invoke-GitSilent -Arguments "ls-remote --heads $cloneUrl refs/heads/arena/*" -TimeoutSeconds 20 -WithOwnerCreds
        if ($lsRes.exit_code -ne 0) { continue }
        $lsOut = @($lsRes.stdout -split "`r?`n")
        foreach ($line in $lsOut) {
            if ($synced -ge 3) { break }
            if ($line -notmatch '^([0-9a-f]{40})\s+refs/heads/(arena/.+)$') { continue }
            $sha    = $Matches[1]
            $branch = $Matches[2].Trim()
            $key    = "{0}#{1}" -f $repoName, $branch
            $shortName = Get-ShortCloneName -RepoName $repoName -Branch $branch

            if ($seen.ContainsKey($key) -and ($seen[$key] -eq $sha)) {
                continue
            }

            $dest = Join-Path $tempRoot ("{0}-{1}" -f $shortName, [guid]::NewGuid().ToString('N').Substring(0, 8))
            try {
                $seen[$key] = $sha
                Save-SeenHeads -Map $seen
                $changed = $true

                $clRes = Invoke-GitSilent -Arguments "clone --quiet --depth 1 --filter=blob:none --sparse --branch $branch $cloneUrl `"$dest`"" -TimeoutSeconds 45 -WithOwnerCreds
                if (($clRes.exit_code -eq 0) -and (Test-Path -LiteralPath (Join-Path $dest '.git'))) {
                    [void](Invoke-GitSilent -Arguments "-C `"$dest`" sparse-checkout set results deliverable code skills" -WorkingDirectory $dest -TimeoutSeconds 45)
                    if (Test-BranchHasPendingWork -ProjectDir $dest -RepoName $repoName) {
                        Write-HubLog "BRANCH-SYNC: $key @ $($sha.Substring(0, 7))"
                        $taskOutcome = Invoke-BranchTasksSilently -ProjectDir $dest -RepoName $repoName -Branch $branch -ShortName $shortName -SourceSha $sha
                        Push-ResultsReceipt -ProjectDir $dest -RepoName $repoName -Branch $branch -ShortName $shortName -SourceSha $sha -TaskOutcome $taskOutcome
                        $headRes = Invoke-GitSilent -Arguments "-C `"$dest`" rev-parse HEAD" -WorkingDirectory $dest -TimeoutSeconds 10
                        $finalSha = ([string]$headRes.stdout).Trim()
                        if ($finalSha -match '^[0-9a-f]{40}$') {
                            $seen[$key] = $finalSha
                            Save-SeenHeads -Map $seen
                        }
                        $synced++
                    } else {
                        Copy-ResultsFromDir -SourceDir $dest -ShortName $ShortName | Out-Null
                    }
                }
            } catch {
                Write-HubLog "WARN: ephemeral sync error on ${key}: $($_.Exception.Message)"
            } finally {
                Remove-TreeSafe -Target $dest | Out-Null
            }
        }
    }

    if ($changed) {
        Save-SeenHeads -Map $seen
    }
    return $synced
}

function Invoke-OneCycle {
    Set-Content -LiteralPath $PidFile -Value ([string]$PID) -Encoding ASCII -ErrorAction SilentlyContinue
    try {
        $dups = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'hub-watch\.ps1' -and $_.ProcessId -ne $PID })
        foreach ($dp in $dups) {
            Stop-Process -Id $dp.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {}

    $script:CgmdCredFile = Find-CgmdCredentialFile
    $syncedNew = Sync-NewRemoteBranches
    $cleanInfo = Invoke-ResultsOnlyCleanup
    $resCount  = @(Get-ChildItem -LiteralPath $ResultsRoot -Directory -ErrorAction SilentlyContinue).Count

    $state = [ordered]@{
        updated_at        = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        host              = $env:COMPUTERNAME
        pid               = $PID
        task_name         = $TaskName
        mode              = 'auto-poll-exec-and-sync-zero-window-v4.5'
        poll_interval_sec = $IntervalSeconds
        sync_root         = $SyncRoot
        results_root      = $ResultsRoot
        base_dir          = (Join-Path $SyncRoot $BaseDirName)
        cred_bridge       = [bool]$script:CgmdCredFile
        result_projects   = $resCount
        synced_new        = $syncedNew
        evicted_clones    = $cleanInfo.evicted_clones
    }
    ($state | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath $StateJson -Encoding UTF8
    Write-HubLog ("CYCLE-DONE: result_projects={0} synced_new={1} cred_bridge={2}" -f $resCount, $syncedNew, [bool]$script:CgmdCredFile)
}

if ($Status) {
    if (Test-Path -LiteralPath $StateJson) {
        Get-Content -LiteralPath $StateJson -Raw
    } else {
        Write-Output "No state file yet at $StateJson"
    }
    return
}

do {
    try {
        Invoke-OneCycle
    } catch {
        Write-HubLog "CYCLE-ERROR: $($_.Exception.Message)"
    }
    if ($Loop) {
        Start-Sleep -Seconds $IntervalSeconds
    }
} while ($Loop)
