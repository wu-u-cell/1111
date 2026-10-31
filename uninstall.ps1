$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains((Join-Path $root 'app.py')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
$links = @((Join-Path ([Environment]::GetFolderPath('Programs')) '生活助手.lnk'), (Join-Path ([Environment]::GetFolderPath('Startup')) '生活助手提醒.lnk'))
foreach ($link in $links) { if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link } }
if (Test-Path -LiteralPath 'HKCU:\Software\Classes\AppUserModelId\LifeAssistant.Desktop') { Remove-Item -LiteralPath 'HKCU:\Software\Classes\AppUserModelId\LifeAssistant.Desktop' }
Write-Output '已移除入口和登录自启动。项目文件及本地待办数据已保留。'
