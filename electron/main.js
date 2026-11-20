'use strict';
// IDEmu desktop: abre a interface em uma janela do Electron. O servidor continua sendo o mesmo (python3 -m idemu gui),
// iniciado aqui como processo filho numa porta livre e encerrado junto com a janela.
const { app, BrowserWindow, dialog, ipcMain, shell, Menu, systemPreferences } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const net = require('net');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');
let server = null, win = null, port = 0, quitting = false;

function freePort(pref) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once('error', () => { const t = net.createServer(); t.listen(0, '127.0.0.1', () => { const p = t.address().port; t.close(() => resolve(p)); }); });
    s.listen(pref, '127.0.0.1', () => s.close(() => resolve(pref)));
  });
}

function waitUp(p, tries = 120) {
  return new Promise((resolve, reject) => {
    const go = (n) => {
      const r = http.get({ host: '127.0.0.1', port: p, path: '/api/state', timeout: 1500 }, (res) => { res.resume(); resolve(); });
      r.on('error', () => (n <= 0 ? reject(new Error('o servidor do IDEmu não respondeu')) : setTimeout(() => go(n - 1), 250)));
      r.on('timeout', () => r.destroy());
    };
    go(tries);
  });
}

function startServer(p) {
  const py = process.env.IDEMU_PYTHON || '/usr/bin/python3';
  server = spawn(py, ['-m', 'idemu', 'gui', '--no-browser', '--port', String(p)], { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  const keep = (d) => { log = (log + d.toString()).slice(-4000); };
  server.stdout.on('data', keep); server.stderr.on('data', keep);
  server.on('exit', (code) => {
    server = null;
    if (!quitting) { dialog.showErrorBox('IDEmu', 'O servidor do IDEmu encerrou (código ' + code + ').\n\n' + log.slice(-1200)); app.quit(); }
  });
}

function stopServer() {
  quitting = true;
  if (server) { try { server.kill('SIGTERM'); } catch (e) { /* já saiu */ } const s = server; setTimeout(() => { try { s.kill('SIGKILL'); } catch (e) { /* ok */ } }, 4000).unref(); }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 920, minWidth: 900, minHeight: 600, title: 'IDEmu', backgroundColor: '#1c1c1e', show: false,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default', trafficLightPosition: { x: 16, y: 16 },
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.once('ready-to-show', () => win.show());
  // links externos abrem no navegador padrão; a janela só navega dentro do próprio servidor
  const here = 'http://127.0.0.1:' + port;
  win.webContents.setWindowOpenHandler(({ url }) => { if (!url.startsWith(here)) shell.openExternal(url); return { action: url.startsWith(here) ? 'allow' : 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(here)) { e.preventDefault(); shell.openExternal(url); } });
  // câmera de ré virtual: a webcam (só vídeo, sem áudio) só é liberada para a própria interface; o resto segue o comportamento padrão do Electron
  win.webContents.session.setPermissionRequestHandler((wc, permission, cb, details) => {
    if (permission !== 'media') return cb(true);
    const types = (details && details.mediaTypes) || [];
    const ok = String((details && details.requestingUrl) || '').startsWith(here) && types.length > 0 && types.every((t) => t === 'video');
    if (!ok) return cb(false);
    if (process.platform !== 'darwin') return cb(true);
    systemPreferences.askForMediaAccess('camera').then(cb, () => cb(false));      // macOS: pede a permissão de câmera ao sistema
  });
  win.loadURL(here + '/');
  win.on('closed', () => { win = null; });
}

ipcMain.handle('idemu:pick', async (ev, o) => {
  o = o || {};
  const kind = o.kind === 'folder' ? 'folder' : o.kind === 'files' ? 'files' : 'file';
  const props = kind === 'folder' ? ['openDirectory', 'createDirectory'] : kind === 'files' ? ['openFile', 'multiSelections'] : ['openFile'];
  const opts = { title: String(o.prompt || ''), message: String(o.prompt || ''), properties: props };
  if (o.start) opts.defaultPath = String(o.start);
  const r = await dialog.showOpenDialog(BrowserWindow.fromWebContents(ev.sender) || win, opts);
  if (r.canceled || !r.filePaths.length) return kind === 'files' ? { paths: [] } : { path: null };
  return kind === 'files' ? { paths: r.filePaths } : { path: r.filePaths[0] };
});

if (!app.requestSingleInstanceLock()) { app.quit(); } else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { role: 'appMenu' }, { role: 'editMenu' },
      { label: 'Visualizar', submenu: [{ role: 'reload' }, { role: 'forceReload' }, { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }, { role: 'toggleDevTools' }] },
      { role: 'windowMenu' },
    ]));
    try {
      port = await freePort(Number(process.env.IDEMU_PORT) || 8765);
      startServer(port);
      await waitUp(port);
      createWindow();
    } catch (e) { dialog.showErrorBox('IDEmu', String(e.message || e)); stopServer(); app.quit(); }
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', stopServer);
  app.on('will-quit', stopServer);
  process.on('SIGTERM', () => { stopServer(); app.quit(); });
  process.on('SIGINT', () => { stopServer(); app.quit(); });
}
