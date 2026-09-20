$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
& .venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
$edgePaths = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
)
if (-not ($edgePaths | Where-Object { Test-Path -LiteralPath $_ })) {
    throw 'Microsoft Edge is required. Install Edge before running the monitor.'
}
Write-Output 'Setup complete. Run .venv\Scripts\python.exe -X utf8 main.py login when ready.'
