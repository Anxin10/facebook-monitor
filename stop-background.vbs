Option Explicit
On Error Resume Next
Dim shell, files, root, python
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(root, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then WScript.Quit 1
shell.CurrentDirectory = root
shell.Run Chr(34) & python & Chr(34) & " -X utf8 " & Chr(34) & files.BuildPath(root, "main.py") & Chr(34) & " stop", 0, False
