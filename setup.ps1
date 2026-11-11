# One-time setup: Python environment (.venv) + the wake-word model (17 MB) and end-of-turn model (9 MB).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $PSScriptRoot '..\LocalAI\bin\uv\uv.exe' }   # the kit ships uv
if (-not (Test-Path $uv)) { throw 'uv not found. Install it (https://docs.astral.sh/uv/) or set up llama-swap-kit first.' }
& $uv sync
if ($LASTEXITCODE) { throw 'uv sync failed' }

$kws = Join-Path $PSScriptRoot 'models\kws'
if (-not (Test-Path (Join-Path $kws 'tokens.txt'))) {
    $name = 'sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01'
    New-Item -ItemType Directory -Force $kws | Out-Null
    curl.exe -L --fail -o "$kws\kws.tar.bz2" "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/$name.tar.bz2"
    if ($LASTEXITCODE) { throw 'wake-word model download failed' }
    & "$env:SystemRoot\System32\tar.exe" -xf "$kws\kws.tar.bz2" -C $kws --strip-components 1   # not a Git/MSYS tar
    if ($LASTEXITCODE) { throw 'could not unpack the wake-word model' }
    Remove-Item "$kws\kws.tar.bz2"
}
$turn = Join-Path $PSScriptRoot 'models\turn\smart-turn-v3.2-cpu.onnx'
if (-not (Test-Path $turn)) {   # Smart Turn v3.2 (Pipecat, BSD-2-Clause): has the speaker finished?
    New-Item -ItemType Directory -Force (Split-Path $turn) | Out-Null
    curl.exe -L --fail -o $turn 'https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx'
    if ($LASTEXITCODE) { throw 'end-of-turn model download failed' }
}
Write-Host 'Ready. Start the inference kit, then run .\run.ps1'
