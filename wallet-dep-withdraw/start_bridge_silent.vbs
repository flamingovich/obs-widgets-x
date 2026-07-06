Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
q = Chr(34)
folder = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd /c cd /d " & q & folder & q & " && pythonw likes_bridge.py --port 8766", 0, False
