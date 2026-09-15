param(
    [string]$Python = "py",
    [switch]$Run,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"

if ($Recreate -and (Test-Path -LiteralPath $VenvPath)) {
    Remove-Item -Recurse -Force -LiteralPath $VenvPath
}

if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python -m venv $VenvPath
}

$VenvPython = Join-Path $VenvPath "Scripts\\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")

if ($Run) {
    & $VenvPython (Join-Path $ProjectRoot "app.py")
}
