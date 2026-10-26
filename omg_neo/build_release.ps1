param([string]$Flutter = 'flutter', [string]$Python = 'python', [string]$PackageName = 'OMG-Neo', [string]$DestinationRoot, [ValidateSet('Release', 'Debug')][string]$Configuration = 'Release')
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
if ($PackageName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
  throw 'PackageName 必须为单个目录名。'
}
if (!$DestinationRoot) { $DestinationRoot = Join-Path $appRoot 'dist' }
$packageRoot = Join-Path $DestinationRoot $PackageName
# Always publish into a fresh folder. Reusing a previous portable release could
# silently retain its AppData, saved paths, or logs even when copying clean files.
if (Test-Path -LiteralPath $packageRoot) {
  throw "分发目录已存在，请使用新的 PackageName：$packageRoot"
}
$appIcon = Join-Path $appRoot 'krr.ico'
if (!(Test-Path -LiteralPath $appIcon -PathType Leaf)) {
  throw '缺少应用图标 krr.ico。'
}
Copy-Item -LiteralPath $appIcon -Destination (Join-Path $appRoot 'windows\runner\resources\krr.ico') -Force
$buildDirectory = "build-distribution-$($Configuration.ToLowerInvariant())"
$taskConfigRoot = Join-Path $appRoot ".build-tools\$Configuration"
New-Item -ItemType Directory -Path $taskConfigRoot -Force | Out-Null
# Isolate Flutter's build-dir preference from the user's global settings. The
# original Release executable may still be running; build in a separate folder.
[IO.File]::WriteAllText((Join-Path $taskConfigRoot '.flutter_settings'),
  "{`"build-dir`":`"$buildDirectory`",`"enable-windows-desktop`":true}",
  [Text.UTF8Encoding]::new($false))
$previousAppData = $env:APPDATA
$previousPreference = $ErrorActionPreference
Push-Location $appRoot
try {
  $env:APPDATA = $taskConfigRoot
  # Same guard as backend\build.ps1: Flutter emits progress and deprecation
  # notices on stderr, which would abort the build under 'Stop'.
  $ErrorActionPreference = 'Continue'
  $mode = "--$($Configuration.ToLowerInvariant())"
  $review = if ($Configuration -eq 'Debug') { 'true' } else { 'false' }
  & $Flutter --suppress-analytics --no-version-check build windows $mode "--dart-define=OMG_UI_REVIEW=$review" --no-tree-shake-icons --no-pub
  if ($LASTEXITCODE -ne 0) { throw "Flutter $Configuration 构建失败。" }
} finally {
  $ErrorActionPreference = $previousPreference
  $env:APPDATA = $previousAppData
  Pop-Location
}
$releaseRoot = Join-Path $appRoot "$buildDirectory\windows\x64\runner\$Configuration"
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
# Copy only Flutter runtime output, never application data from a test run.
Get-ChildItem -LiteralPath $releaseRoot -Force |
  Where-Object {
    ($_.PSIsContainer -and $_.Name -eq 'data') -or
    (!$_.PSIsContainer -and ($_.Name -eq 'omg_neo.exe' -or
      $_.Extension -eq '.dll' -or $_.Name -eq 'native_assets.json'))
  } |
  Copy-Item -Destination $packageRoot -Recurse -Force
& (Join-Path (Split-Path $appRoot) 'backend\build.ps1') -Python $Python -Output (Join-Path $packageRoot 'backend')
$privateFiles = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -Force |
  Where-Object {
    $_.Name -in @('AppData', 'config.json', 'config.json.bak', 'loader_config.json', '.backend.lock') -or
    (!$_.PSIsContainer -and $_.Extension -in @('.log', '.bak'))
  })
if ($privateFiles.Count -gt 0) {
  throw '分发检查失败：检测到配置或运行数据，未生成压缩包。'
}
Write-Output "完整应用：$(Join-Path $packageRoot 'omg_neo.exe')"
