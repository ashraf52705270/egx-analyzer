Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run "taskkill /f /im python.exe /t", 0, True
