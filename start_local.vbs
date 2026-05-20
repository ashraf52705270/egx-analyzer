Dim shell, fso, dir, pythonPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonPath = dir & "\main.py"

' تشغيل السيرفر مخفي
shell.Run "python """ & pythonPath & """", 0, False

' انتظار 4 ثواني وفتح المتصفح
WScript.Sleep 4000
shell.Run "http://localhost:8000"
