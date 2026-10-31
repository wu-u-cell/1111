$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
$title = [System.Security.SecurityElement]::Escape($env:LIFE_TITLE)
$body = [System.Security.SecurityElement]::Escape($env:LIFE_BODY)
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual><audio silent='true'/></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$toast.Tag = 'deadline'
$toast.Group = 'lifeassistant'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('LifeAssistant.Desktop').Show($toast)
