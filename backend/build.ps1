param([string]$Python = 'python', [string]$Output)
$ErrorActionPreference = 'Stop'
$backendRoot = $PSScriptRoot
if (!$Output) {
  $Output = Join-Path (Split-Path $backendRoot) 'omg_neo\build\windows\x64\runner\Release\backend'
}
if ((Test-Path -LiteralPath $Output) -and
    (Get-ChildItem -LiteralPath $Output -Force | Select-Object -First 1)) {
  throw "后端分发目录必须为空，以免旧依赖残留：$Output"
}
$distRoot = Join-Path $backendRoot 'dist'
# PyInstaller streams its whole progress log to stderr. Under
# $ErrorActionPreference='Stop' PowerShell treats the first non-fatal INFO line
# as a terminating error, so relax it around native calls only. The exit code
# checked below stays the single source of truth for build success.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
  & $Python -m PyInstaller --noconfirm --clean `
    --distpath $distRoot --workpath (Join-Path $backendRoot 'build') `
    (Join-Path $backendRoot 'neo_hosts.spec')
} finally {
  $ErrorActionPreference = $previousPreference
}
if ($LASTEXITCODE -ne 0) { throw 'Python 后端打包失败。' }
# neo_hosts.spec performs dependency filtering before collecting the bundle.
New-Item -ItemType Directory -Path $Output -Force | Out-Null
Copy-Item -Path (Join-Path $distRoot 'omg_backend\*') -Destination $Output -Recurse -Force
Write-Output "后端已发布：$Output"
