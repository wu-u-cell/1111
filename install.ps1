param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = (Get-Command python.exe -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (!(Test-Path -LiteralPath $pythonw)) { throw '需要 Python 3 和 pythonw.exe。' }
& $python -c 'import sqlite3'
if ($LASTEXITCODE -ne 0) { throw 'Python 缺少 sqlite3。' }
Add-Type -AssemblyName System.Drawing
$iconPath = Join-Path $root 'assistant.ico'
if (!(Test-Path -LiteralPath $iconPath)) {
    $bitmap = New-Object System.Drawing.Bitmap 64,64
    $g = [System.Drawing.Graphics]::FromImage($bitmap)
    $g.SmoothingMode = 'AntiAlias'
    $g.Clear([System.Drawing.Color]::FromArgb(35,102,87))
    $font = New-Object System.Drawing.Font 'Microsoft YaHei UI',31,([System.Drawing.FontStyle]::Bold)
    $g.DrawString('生',$font,[System.Drawing.Brushes]::White,3,3)
    $icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
    $stream = [IO.File]::Create($iconPath)
    $icon.Save($stream)
    $stream.Dispose(); $icon.Dispose(); $g.Dispose(); $bitmap.Dispose(); $font.Dispose()
}
$appKey = 'HKCU:\Software\Classes\AppUserModelId\LifeAssistant.Desktop'
New-Item -Path $appKey -Force | Out-Null
New-ItemProperty -Path $appKey -Name DisplayName -Value '生活助手' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $appKey -Name IconUri -Value $iconPath -PropertyType String -Force | Out-Null
$programs = [Environment]::GetFolderPath('Programs')
$startup = [Environment]::GetFolderPath('Startup')
$shell = New-Object -ComObject WScript.Shell
function New-AssistantLink($path, $arguments, $description) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = $arguments
    $link.WorkingDirectory = $root
    $link.Description = $description
    $link.IconLocation = "$iconPath,0"
    $link.Save()
}
New-AssistantLink (Join-Path $programs '生活助手.lnk') ('"' + (Join-Path $root 'app.py') + '"') '待办、截止日期、书单和国际新闻'
New-AssistantLink (Join-Path $startup '生活助手提醒.lnk') ('"' + (Join-Path $root 'app.py') + '" --reminders') '仅在你设置的 DDL 时间发送通知'
Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $root 'app.py') + '" --reminders') -WindowStyle Hidden
if (!$NoLaunch) {
    Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $root 'app.py') + '"') -WindowStyle Hidden
}
Write-Output '已安装。Windows 开始菜单搜索：生活助手'
Write-Output "项目位置：$root"
