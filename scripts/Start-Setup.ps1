$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskLauncher = Join-Path $taskRoot '.venv\Scripts\family-harness.exe'
if (-not (Test-Path -LiteralPath $taskLauncher)) {
    throw 'First run Install-Windows.cmd in the project folder, then launch setup again.'
}
& $taskLauncher setup
exit $LASTEXITCODE
