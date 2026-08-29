[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$distPath = Join-Path $projectRoot "dist"
$buildPath = Join-Path $projectRoot "build"
$entryPoint = Join-Path $projectRoot "main.pyw"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found at $python. Create the virtual environment and install requirements first."
}

& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller is not installed; installing it in the project virtual environment..."
    & $python -m pip install "PyInstaller>=6.0"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install PyInstaller."
    }
}

Write-Host "Building AudiobookForge.exe..."
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name AudiobookForge `
    --distpath $distPath `
    --workpath $buildPath `
    --specpath $buildPath `
    $entryPoint

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$executable = Join-Path $distPath "AudiobookForge.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Build completed without producing $executable."
}

Write-Host "Build complete: $executable"
Write-Host "The executable was not launched. Place ffmpeg.exe and ffprobe.exe beside it, or configure them from the Tools menu."
