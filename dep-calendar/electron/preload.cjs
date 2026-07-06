const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  writeClipboard: (text) => ipcRenderer.invoke("clipboard-write", text),
  saveBackupDialog: (jsonText) => ipcRenderer.invoke("save-backup-dialog", jsonText),
  loadBackupDialog: () => ipcRenderer.invoke("load-backup-dialog"),
  savePngDialog: (payload) => ipcRenderer.invoke("save-png-dialog", payload),
});
