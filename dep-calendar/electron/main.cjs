const { app, BrowserWindow, ipcMain, clipboard, dialog } = require("electron");
const path = require("path");
const fs = require("fs");

const isDev = !app.isPackaged;

function createWindow() {
  const win = new BrowserWindow({
    width: 1100,
    height: 800,
    minWidth: 720,
    minHeight: 560,
    backgroundColor: "#0f1115",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
  });

  if (isDev) {
    win.loadURL("http://localhost:5173");
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

ipcMain.handle("clipboard-write", (_, text) => {
  clipboard.writeText(String(text ?? ""));
  return true;
});

ipcMain.handle("save-backup-dialog", async (_, jsonText) => {
  const { canceled, filePath } = await dialog.showSaveDialog({
    title: "Сохранить резервную копию",
    defaultPath: `dep-calendar-backup-${new Date().toISOString().slice(0, 10)}.json`,
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (canceled || !filePath) return { ok: false };
  try {
    fs.writeFileSync(filePath, jsonText, "utf8");
    return { ok: true, path: filePath };
  } catch (e) {
    return { ok: false, error: String(e?.message ?? e) };
  }
});

ipcMain.handle("save-png-dialog", async (event, payload) => {
  const base64Raw =
    payload && typeof payload.base64 === "string" ? payload.base64 : "";
  const base64 = base64Raw.replace(/\s/g, "");
  const defaultPath =
    (payload && payload.defaultPath) ||
    `dep-calendar-${new Date().toISOString().slice(0, 10)}.png`;
  const win = BrowserWindow.fromWebContents(event.sender);
  const { canceled, filePath } = await dialog.showSaveDialog(win ?? undefined, {
    title: "Сохранить изображение",
    defaultPath,
    filters: [{ name: "PNG", extensions: ["png"] }],
  });
  if (canceled || !filePath) return { ok: false };
  if (!base64) return { ok: false, error: "Пустые данные изображения" };
  try {
    const buf = Buffer.from(base64, "base64");
    if (!buf.length) return { ok: false, error: "Некорректный PNG (base64)" };
    fs.writeFileSync(filePath, buf);
    return { ok: true, path: filePath };
  } catch (e) {
    return { ok: false, error: String(e?.message ?? e) };
  }
});

ipcMain.handle("load-backup-dialog", async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    title: "Загрузить резервную копию",
    properties: ["openFile"],
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (canceled || !filePaths?.[0]) return { ok: false };
  try {
    const text = fs.readFileSync(filePaths[0], "utf8");
    return { ok: true, text, path: filePaths[0] };
  } catch (e) {
    return { ok: false, error: String(e?.message ?? e) };
  }
});

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
