param([switch]$Resources)
$executable = Join-Path $PSScriptRoot 'dist\OMG-Neo\omg_neo.exe'
if (!(Test-Path -LiteralPath $executable)) {
  throw '请先在本项目目录执行 .\build_release.ps1，生成包含 Python 后端的完整应用。'
}
if ($Resources) {
  Start-Process -WindowStyle Hidden -FilePath $executable -WorkingDirectory $PSScriptRoot -ArgumentList '--resources'
} else {
  Start-Process -WindowStyle Hidden -FilePath $executable -WorkingDirectory $PSScriptRoot
}



