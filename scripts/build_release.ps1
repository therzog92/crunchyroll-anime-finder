# Build Windows release (run from repo root)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Installing build dependencies..."
python -m pip install -r requirements.txt -r requirements-build.txt -q

Write-Host "Building executable..."
python -m PyInstaller --noconfirm --clean `
    --windowed `
    --name "CrunchyrollAnimeFinder" `
    --paths "$Root" `
    --hidden-import=PIL `
    --hidden-import=PIL.Image `
    --hidden-import=PIL.ImageTk `
    --collect-submodules=playwright `
    run.py

$distDir = Join-Path $Root "dist\CrunchyrollAnimeFinder"
$zipPath = Join-Path $Root "dist\CrunchyrollAnimeFinder-Windows.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $distDir -DestinationPath $zipPath -Force

Write-Host "Done:"
Write-Host "  Folder: $distDir"
Write-Host "  Zip:    $zipPath"
