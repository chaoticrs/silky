# Optional but recommended: add the three models the assistant uses beyond the kit's defaults
# (embeddings, a faster speech-to-text setting, the d1 decision model; about 1.6 GB). See kit_setup.py.
$ErrorActionPreference = 'Stop'
$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw 'Run setup.ps1 first.' }
& $python "$PSScriptRoot\kit_setup.py"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
