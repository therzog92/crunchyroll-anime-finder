# Build single-file Windows release (run from repo root)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Installing build dependencies..."
python -m pip install -r requirements.txt -r requirements-build.txt -q

$exeName = "CrunchyrollAnimeFinder.exe"
$exePath = Join-Path $Root "dist\$exeName"

Write-Host "Building single-file executable..."
python -m PyInstaller --noconfirm --clean `
    --onefile `
    --windowed `
    --name "CrunchyrollAnimeFinder" `
    --paths "$Root" `
    --hidden-import=PIL `
    --hidden-import=PIL.Image `
    --hidden-import=PIL.ImageTk `
    --collect-all playwright `
    run.py

if (-not (Test-Path $exePath)) {
    throw "Build failed: $exePath not found"
}

$sizeMb = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "Done: $exePath ($sizeMb MB)"
