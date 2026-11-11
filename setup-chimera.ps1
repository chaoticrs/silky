# Optional: build the Chimera voice (physical-modelling synth, https://github.com/jamesondh/chimera-vocal-synth).
# Everything lands under engines\ : the source, a private Rust toolchain (about 700 MB, not added to PATH),
# and the result engines\chimera\{chimera-say.exe, cmudict.txt.gz, head.js}. head.js is Chimera's own 3D head for
# the overlay (needs Node/npm at build time only; skipped without it). Delete engines\rust afterwards if you like.
#   -HeadOnly  re-bundle head.js after editing engines\chimera-head (needs npm only, no Rust)
param([switch]$HeadOnly)
$ErrorActionPreference = 'Stop'
$eng = Join-Path $PSScriptRoot 'engines'
$src = Join-Path $eng 'chimera-src'
if (-not (Test-Path $src)) { git clone --depth 1 https://github.com/jamesondh/chimera-vocal-synth $src }

$out = Join-Path $eng 'chimera'
$head = Join-Path $eng 'chimera-head'
if (-not $HeadOnly) {
$env:RUSTUP_HOME = Join-Path $eng 'rust\rustup'
$env:CARGO_HOME = Join-Path $eng 'rust\cargo'
$cargo = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path $cargo)) {
    New-Item -ItemType Directory -Force (Join-Path $eng 'rust') | Out-Null
    $init = Join-Path $eng 'rust\rustup-init.exe'
    curl.exe -sSL --fail -o $init https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe
    if ($LASTEXITCODE) { throw 'rustup download failed' }
    # the gnu toolchain brings its own linker, so no Visual Studio is needed
    & $init -y --no-modify-path --profile minimal --default-host x86_64-pc-windows-gnu --default-toolchain stable
    if ($LASTEXITCODE) { throw 'rust install failed' }
}
$env:PATH = "$(Join-Path $env:CARGO_HOME 'bin');$env:PATH"
& $cargo build --release --manifest-path (Join-Path $eng 'chimera-say\Cargo.toml')
if ($LASTEXITCODE) { throw 'chimera-say build failed' }

New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item (Join-Path $eng 'chimera-say\target\release\chimera-say.exe') $out -Force
Copy-Item (Join-Path $src 'public\data\cmudict.txt.gz') $out -Force

# the engine as wasm, for the overlay's head
    & (Join-Path $env:CARGO_HOME 'bin\rustup.exe') target add wasm32-unknown-unknown
    if ($LASTEXITCODE) { throw 'adding the wasm target failed' }
    & $cargo build -p chimera-wasm --release --target wasm32-unknown-unknown --manifest-path (Join-Path $src 'Cargo.toml')
    if ($LASTEXITCODE) { throw 'wasm build failed' }
    Copy-Item (Join-Path $src 'target\wasm32-unknown-unknown\release\chimera_wasm.wasm') (Join-Path $out 'chimera.wasm') -Force
}

# The overlay's head: Chimera's renderer + chimera.wasm, bundled into one script (engines\chimera-head).
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location $head
    try {
        npm install --no-audit --no-fund --loglevel=error
        if ($LASTEXITCODE) { throw 'npm install failed' }
        $env:NODE_PATH = Join-Path $head 'node_modules'   # Chimera's sources import three from outside this folder
        npx --no-install esbuild head.ts --bundle --format=iife --minify --target=es2022 --loader:.wasm=binary `
            '--external:*.wasm?url' --log-level=warning "--outfile=$(Join-Path $out 'head.js')"
        if ($LASTEXITCODE) { throw 'bundling the head failed' }
    } finally { Pop-Location }
} else { Write-Host 'npm not found: skipping the overlay head (the Chimera persona will use the plain overlay)' }
Write-Host "Chimera voice built: $out"
