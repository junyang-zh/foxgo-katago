param([int]$Port = 8173)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$trainerPython = Get-Command python -ErrorAction SilentlyContinue
if ($trainerPython) {
    & $trainerPython.Source -m trainer.server --port $Port
} elseif (Test-Path -LiteralPath "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe") {
    & "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" -m trainer.server --port $Port
} else {
    Write-Error 'Install Python 3.10 or later, then run python -m trainer.server.'
}
