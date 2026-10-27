param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$updaterRoot = $PSScriptRoot
$previousPreference = $ErrorActionPreference
try {
  $ErrorActionPreference = 'Continue'
  & $Python -m PyInstaller --noconfirm --clean --onefile --console `
    --name OMG-Neo-Updater --icon (Join-Path $updaterRoot '..\omg_neo\krr.ico') `
    --paths (Join-Path $updaterRoot '..\OMGLite\src') `
    --distpath (Join-Path $updaterRoot 'dist') --workpath (Join-Path $updaterRoot 'build') `
    --specpath (Join-Path $updaterRoot 'build') (Join-Path $updaterRoot 'main.py')
  if ($LASTEXITCODE -ne 0) { throw 'Updater 构建失败。' }
} finally {
  $ErrorActionPreference = $previousPreference
}
$executable = Join-Path $updaterRoot 'dist\OMG-Neo-Updater.exe'
$hash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$executable.sha256", "$hash  OMG-Neo-Updater.exe`n", [Text.Encoding]::ASCII)
Write-Output "TUI 更新器：$executable"
