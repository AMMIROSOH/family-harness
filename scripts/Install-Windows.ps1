# Explicit installation only: no microphone, browser, models, services, or auto-start.
$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Use Windows 10/11 x64 for this preview.' }
Write-Host 'Installing the room-audio and English speech preview libraries. Python is downloaded if needed.'
Write-Host 'Allow roughly 70-130 MB of downloads on a fresh machine. Voice models are installed separately.'
Write-Host 'Audio will remain off. Run Start-Setup.cmd after installation.'
$taskUv = Join-Path $taskRoot '.local\tools\bin\uv.exe'
if (-not (Test-Path -LiteralPath $taskUv)) {
    $taskUvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($taskUvCommand) {
        $taskUv = $taskUvCommand.Source
    } else {
        # Official versioned uv installer, confined to this checkout, without PATH changes.
        $taskTools = Join-Path $taskRoot '.local\tools\bin'
        New-Item -ItemType Directory -Path $taskTools -Force | Out-Null
        $taskInstaller = Join-Path $taskRoot '.local\install-uv.ps1'
        Invoke-WebRequest -Uri 'https://astral.sh/uv/0.13.0/install.ps1' -OutFile $taskInstaller
        $taskOldInstallDir = $env:UV_INSTALL_DIR
        $taskOldModifyPath = $env:UV_NO_MODIFY_PATH
        try {
            $env:UV_INSTALL_DIR = $taskTools
            $env:UV_NO_MODIFY_PATH = '1'
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $taskInstaller
            if ($LASTEXITCODE -ne 0) { throw 'uv installation failed. Check your internet connection.' }
        } finally {
            $env:UV_INSTALL_DIR = $taskOldInstallDir
            $env:UV_NO_MODIFY_PATH = $taskOldModifyPath
        }
    }
}
Push-Location -LiteralPath $taskRoot
try {
    & $taskUv sync --locked --no-dev --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Installation failed. Check internet access and free disk space, then retry.' }
    & (Join-Path $taskRoot '.venv\Scripts\family-harness.exe') --version
    if ($LASTEXITCODE -ne 0) { throw 'The installation could not be verified.' }
    Write-Host 'Installed. Start-Setup.cmd opens local setup when you choose to launch it.'
} finally { Pop-Location }
