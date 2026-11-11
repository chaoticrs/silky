# One-time setup: Python environment (.venv) + the wake-word model (17 MB) and end-of-turn model (9 MB).
# Needs llama-swap-kit (https://github.com/chaoticrs/llama-swap-kit) set up in a folder next to this one.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# uv builds the Python environment. Use the one on PATH, or the one the kit ships.
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
foreach ($kit in '..\llama-swap-kit', '..\LocalAI') {
    if (-not $uv -and (Test-Path "$PSScriptRoot\$kit\bin\uv\uv.exe")) { $uv = "$PSScriptRoot\$kit\bin\uv\uv.exe" }
}
if (-not $uv) {
    throw "uv was not found. Either set up llama-swap-kit in a folder next to this one (it ships uv), or install uv: https://docs.astral.sh/uv/"
}
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
Write-Host ''
Write-Host 'Ready. Next:'
Write-Host '  .\setup-kit.ps1      adds the models for instant commands, file search and the screen (recommended, 1.6 GB)'
Write-Host '  .\run.ps1 --doctor   checks everything'
Write-Host '  .\run.ps1            starts the assistant: say "Silky"'
