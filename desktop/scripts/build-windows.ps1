<#
  AETHER 1.0 FINAL – one-command Windows build (Tauri 2 shell + PyInstaller backend sidecar).

  Usage (PowerShell, from anywhere):
      powershell -ExecutionPolicy Bypass -File desktop\scripts\build-windows.ps1 [-SkipTests] [-MakeNsis <path>] [-WebView2Installer <path>]
  or simply double-click BUILD_WINDOWS.bat in the project root.

  Result:
      dist-windows\AETHER_SETUP.exe          per-user installer (no admin rights)
      dist-windows\portable\AETHER.exe       + aether-backend.exe (keep both in one folder)

  Prerequisites (one-time, internet needed only for these installs and the first npm / pip / cargo download):
      Node.js 20+            winget install OpenJS.NodeJS.LTS
      Python 3.11–3.13 x64   winget install Python.Python.3.12
      Rust (MSVC)            winget install Rustlang.Rustup   →  rustup default stable-msvc
      VS 2022 Build Tools    winget install Microsoft.VisualStudio.2022.BuildTools  (workload "Desktop development with C++")
      NSIS (optional)        winget install NSIS.NSIS   – without it, Tauri's own NSIS bundler is used
#>
param(
    [string] $MakeNsis = '',
    [string] $WebView2Installer = '',
    [switch] $SkipTests
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$version = '1.0.0'

function Run($command, [string[]] $arguments) {
    Write-Host "› $command $($arguments -join ' ')" -ForegroundColor DarkCyan
    & $command @arguments
    if ($LASTEXITCODE -ne 0) { throw "$command $arguments exited with $LASTEXITCODE" }
}
function Need($cmd, $hint) {
    if (!(Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Missing prerequisite '$cmd'. $hint" }
}
function Find-Python {
    foreach ($v in '3.12', '3.11', '3.13') {
        try { $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() } } catch { }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python 3.11–3.13 (x64) not found. Install: winget install Python.Python.3.12"
}

Need node  'Install Node.js 20+: winget install OpenJS.NodeJS.LTS'
Need npm.cmd 'Node.js installation is incomplete (npm missing).'
Need cargo 'Install Rust: winget install Rustlang.Rustup, then: rustup default stable-msvc'
Need rustc 'Install Rust: winget install Rustlang.Rustup'

Push-Location $root
try {
    # ---------------------------------------------------------------- Python environment for the sidecar
    $venvPy = "$root\desktop\backend\.venv\Scripts\python.exe"
    if (!(Test-Path $venvPy)) { $basePy = Find-Python; Run $basePy @('-m', 'venv', 'desktop\backend\.venv') }
    Run $venvPy @('-m', 'pip', 'install', '--upgrade', 'pip')
    Run $venvPy @('-m', 'pip', 'install', '-r', 'desktop/backend/requirements-desktop.txt', 'pytest', 'httpx')

    # ---------------------------------------------------------------- checks
    Set-Location "$root\web\frontend"
    Run npm.cmd @('install', '--no-audit', '--no-fund')
    if (!$SkipTests) {
        Run npm.cmd @('run', 'typecheck')
        Run npm.cmd @('test')
        Set-Location "$root\web\backend"
        Run $venvPy @('-m', 'pytest', '-q')
    }

    # ---------------------------------------------------------------- sidecar + shell
    Set-Location "$root\desktop"
    $env:PYTHON = $venvPy
    Run npm.cmd @('install', '--no-audit', '--no-fund')
    # Always rebuild the final RAR-derived React UI (including spacecraft GLB and Draco-free skeleton).
    # A precompiled dist from earlier versions must never become the packaged Windows frontend.
    Run npm.cmd @('run', 'build:frontend')
    Run npm.cmd @('run', 'build:backend')
    if (!$SkipTests) {
        $sidecar = Get-ChildItem "$root\desktop\src-tauri\binaries\aether-backend-*.exe" | Select-Object -First 1
        $env:AETHER_SIDECAR = $sidecar.FullName
        Run $venvPy @('-m', 'pytest', 'tests', '-q')
        Remove-Item Env:\AETHER_SIDECAR
    }

    $out = "$root\dist-windows"
    New-Item -ItemType Directory -Force "$out\portable" | Out-Null
    $target = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { "$root\desktop\src-tauri\target" }

    if (!$MakeNsis) {
        $cmd = Get-Command makensis -ErrorAction SilentlyContinue
        if ($cmd) { $MakeNsis = $cmd.Source }
        elseif (Test-Path "${env:ProgramFiles(x86)}\NSIS\makensis.exe") { $MakeNsis = "${env:ProgramFiles(x86)}\NSIS\makensis.exe" }
    }
    if ($MakeNsis) {
        # Local NSIS: no downloads during packaging.
        Run npx.cmd @('tauri', 'build', '--no-bundle')
        $nsisArgs = @("/DAPP=$target\release\aether-desktop.exe", "/DBACKEND=$target\release\aether-backend.exe", "/DOUTPUT=$out\AETHER_SETUP.exe")
        if ($WebView2Installer) { $nsisArgs += "/DWEBVIEW2=$((Resolve-Path $WebView2Installer).Path)" }
        Run $MakeNsis ($nsisArgs + @('scripts\installer-local.nsi'))
    } else {
        # Tauri's bundler (downloads NSIS tooling on first use).
        Run npx.cmd @('tauri', 'build', '--bundles', 'nsis')
        $setup = Get-ChildItem "$target\release\bundle\nsis\AETHER_*_x64-setup.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
        Copy-Item $setup.FullName "$out\AETHER_SETUP.exe" -Force
    }
    Copy-Item "$target\release\aether-desktop.exe" "$out\portable\AETHER.exe" -Force
    Copy-Item "$target\release\aether-backend.exe" "$out\portable\aether-backend.exe" -Force

    Write-Host ""
    Write-Host "AETHER $version built:" -ForegroundColor Green
    Get-Item "$out\AETHER_SETUP.exe", "$out\portable\AETHER.exe", "$out\portable\aether-backend.exe" | Format-Table Name, Length, LastWriteTime
} finally { Pop-Location }
