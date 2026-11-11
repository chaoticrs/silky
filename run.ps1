# Start the assistant. Starts the inference kit first if it is not running (in its own minimized window).
# Arguments pass through:   .\run.ps1 --text "what time is it"    .\run.ps1 --doctor    .\run.ps1 --index
Set-Location $PSScriptRoot
$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw 'Not set up yet. Run: powershell -ExecutionPolicy Bypass -File setup.ps1' }

# the kit's address and folder come from config.toml ([kit] url / folder)
$config = Get-Content "$PSScriptRoot\config.toml" -Raw
$url = if ($config -match '(?m)^url\s*=\s*"([^"]+)"') { $Matches[1] } else { 'http://127.0.0.1:8080' }
$folders = @(if ($config -match '(?m)^folder\s*=\s*"([^"]+)"') { $Matches[1] }) + '..\llama-swap-kit', '..\LocalAI'
function Test-Kit { try { (Invoke-WebRequest "$url/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } }

if (-not (Test-Kit)) {
    $start = $folders | ForEach-Object { Join-Path $PSScriptRoot "$_\start.ps1" } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $start) { throw "The inference kit is not running and was not found next to this folder. Set it up (https://github.com/chaoticrs/llama-swap-kit) or point [kit] folder in config.toml at it." }
    Write-Host 'Starting the inference kit...'
    Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$start`""
    foreach ($i in 1..60) { if (Test-Kit) { break }; Start-Sleep 1 }
    if (-not (Test-Kit)) { throw 'The inference kit did not come up within a minute; look at its window.' }
}
& $python -m agentd @args
