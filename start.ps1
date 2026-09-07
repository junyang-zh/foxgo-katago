param([int]$Port = 8173, [switch]$Background, [switch]$Administrator)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Administrator) {
    $trainerIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $trainerPrincipal = [Security.Principal.WindowsPrincipal]::new($trainerIdentity)
    if (!$trainerPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $trainerScript = Join-Path $PSScriptRoot 'start.ps1'
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $trainerScript + '"'),'-Background','-Port',$Port)
        Write-Output 'Approve the Windows UAC prompt to start the trainer at the same privilege level as FoxGo.'
        return
    }
}
$trainerPython = Get-Command python -ErrorAction SilentlyContinue
if ($trainerPython) {
    $trainerExecutable = $trainerPython.Source
} elseif (Test-Path -LiteralPath "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe") {
    $trainerExecutable = "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
} else {
    Write-Error 'Install Python 3.10 or later, then run python -m trainer.server.'
}
if ($Background) {
    try {
        $existingTrainer = Invoke-RestMethod "http://127.0.0.1:$Port/api/state" -TimeoutSec 2
        if ($existingTrainer.token) {
            Write-Output "Trainer already running at http://127.0.0.1:$Port"
            return
        }
    } catch { }
    $trainerData = Join-Path $PSScriptRoot 'data'
    New-Item -ItemType Directory -Force -Path $trainerData | Out-Null
    $trainerProcess = Start-Process -FilePath $trainerExecutable -ArgumentList '-m','trainer.server','--port',$Port -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $trainerData 'server.stdout.log') -RedirectStandardError (Join-Path $trainerData 'server.stderr.log') -PassThru
    Write-Output "Trainer started in background (PID $($trainerProcess.Id)): http://127.0.0.1:$Port"
    Write-Output "KataGo starts automatically. Select a connector in the panel. To stop: Stop-Process -Id $($trainerProcess.Id)"
} else {
    & $trainerExecutable -m trainer.server --port $Port
}
