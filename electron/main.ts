import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, shell } from 'electron';
import * as path from 'path';
import * as keytar from 'keytar';
import { SidecarManager, TOKEN_HEADER } from './sidecar';

const KEYTAR_SERVICE = 'MeetingPal';
const KEYTAR_ACCOUNT = 'anthropic-api-key';
const GEMINI_ACCOUNT = 'gemini-api-key';
const DEEPGRAM_ACCOUNT = 'deepgram-api-key';

const sidecar = new SidecarManager();
let mainWindow: BrowserWindow | null = null;
let wsConnection: import('ws').WebSocket | null = null;
let quitting = false;

// ── Window ────────────────────────────────────────────────────────────────────

function createWindow(customTitlebar: boolean): void {
  // `frame` is fixed at creation; when the custom title bar is on we drop the OS
  // frame + menu and the renderer draws its own bar. Window stays resizable.
  if (customTitlebar) {
    Menu.setApplicationMenu(null);
  }
  mainWindow = new BrowserWindow({
    width: 400,  // launch in the compact "mini" layout (narrow mode triggers < 450px)
    height: 900,
    minWidth: 400,
    minHeight: 535,
    backgroundColor: '#111827',
    frame: !customTitlebar,
    resizable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    mainWindow.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`)
    );
  }

  // Forward renderer console warnings/errors + load failures to the main process log
  // so a blank/broken renderer is diagnosable from the terminal (the detached devtools
  // is easy to miss). Cheap and dev-only-noisy; keep it.
  mainWindow.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    if (level >= 2) console.log(`[renderer-console] ${message} (${sourceId}:${line})`);
  });
  mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
    console.log(`[did-fail-load] ${code} ${desc} ${url}`);
  });
  mainWindow.webContents.on('render-process-gone', (_e, details) => {
    console.log(`[render-process-gone] ${JSON.stringify(details)}`);
  });

  // The app is a single local page: never open new windows, never navigate away from it.
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = MAIN_WINDOW_VITE_DEV_SERVER_URL
      ? url.startsWith(MAIN_WINDOW_VITE_DEV_SERVER_URL)
      : url.startsWith('file://');
    if (!allowed) event.preventDefault();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── WebSocket connection to sidecar ───────────────────────────────────────────

function connectWebSocket(): void {
  const WebSocket = require('ws');
  const ws = new WebSocket(`ws://127.0.0.1:${sidecar.port}/ws?token=${sidecar.token}`);
  wsConnection = ws;

  ws.on('message', (raw: Buffer) => {
    try {
      const msg = JSON.parse(raw.toString());
      if (!mainWindow) return;
      switch (msg.type) {
        case 'transcript_segment':
          mainWindow.webContents.send('transcript-segment', msg);
          break;
        case 'transcript_remove':
          mainWindow.webContents.send('transcript-remove', msg);
          break;
        case 'audio_level':
          mainWindow.webContents.send('audio-level', msg);
          break;
        case 'session_status':
          mainWindow.webContents.send('session-status', msg);
          break;
        case 'error':
          mainWindow.webContents.send('sidecar-error', msg);
          break;
        case 'model_download_progress':
          mainWindow.webContents.send('model-download-progress', msg);
          break;
        case 'auto_answer_start':
          mainWindow.webContents.send('auto-answer-start', msg);
          break;
        case 'auto_answer_token':
          mainWindow.webContents.send('auto-answer-token', msg);
          break;
        case 'auto_answer_done':
          mainWindow.webContents.send('auto-answer-done', msg);
          break;
        case 'auto_answer_error':
          mainWindow.webContents.send('auto-answer-error', msg);
          break;
      }
    } catch {
      // ignore malformed messages
    }
  });

  ws.on('close', () => {
    if (!quitting) setTimeout(connectWebSocket, 2000);
  });
  ws.on('error', () => {
    /* reconnect handled by close */
  });
}

// ── API request helper ────────────────────────────────────────────────────────

const API_TIMEOUT_MS = 8000;
// Start connects to audio devices (and cloud sockets); stop finishes the last decode and
// saves the session. Both legitimately take longer than an ordinary request.
const SLOW_API_TIMEOUT_MS = 45000;
const SLOW_PATHS = new Set(['/api/session/start', '/api/session/stop']);

async function apiRequest<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  // Time-bound the request: without this, a crashed/unreachable sidecar makes fetch
  // hang forever, which left the Stop button stuck.
  const timeoutMs = SLOW_PATHS.has(path) ? SLOW_API_TIMEOUT_MS : API_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${sidecar.baseUrl}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', [TOKEN_HEADER]: sidecar.token },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Sidecar ${method} ${path} → ${res.status}: ${text}`);
    }
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw new Error(`Sidecar ${method} ${path} timed out after ${timeoutMs}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// ── IPC Handlers ─────────────────────────────────────────────────────────────

ipcMain.handle('get-devices', () => apiRequest('GET', '/api/devices'));

ipcMain.handle('start-session', (_e, options) =>
  apiRequest('POST', '/api/session/start', options)
);

ipcMain.handle('stop-session', () => apiRequest('POST', '/api/session/stop', {}));

ipcMain.handle('ask-question', async (_e, { question, sessionId, model }) => {
  // The Claude key goes only to the one endpoint that needs it, as a per-request header.
  const apiKey = await keytar.getPassword(KEYTAR_SERVICE, KEYTAR_ACCOUNT);
  const preferences = await apiRequest<{ claude_model: string }>('GET', '/api/preferences');
  const claudeModel = model || preferences.claude_model || 'claude-sonnet-4-6';

  const res = await fetch(`${sidecar.baseUrl}/api/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      [TOKEN_HEADER]: sidecar.token,
      ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
    },
    body: JSON.stringify({ question, session_id: sessionId, claude_model: claudeModel }),
  });

  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Ask failed: ${res.status} ${detail}`.trim());
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;

  const handlePart = (part: string) => {
    const dataLine = part.split('\n').find((l) => l.startsWith('data:'));
    const eventLine = part.split('\n').find((l) => l.startsWith('event:'));
    if (!dataLine) return;
    try {
      const event = JSON.parse(dataLine.slice(5).trim());
      const eventType = eventLine ? eventLine.slice(6).trim() : 'content_delta';
      if (eventType === 'content_delta' && event.text) {
        mainWindow?.webContents.send('ai-token', event.text);
      } else if (eventType === 'message_stop') {
        finished = true;
        mainWindow?.webContents.send('ai-done', event);
      } else if (eventType === 'error') {
        finished = true;
        mainWindow?.webContents.send('sidecar-error', {
          type: 'error', code: 'ask_failed', message: event.message ?? 'Ask failed', recoverable: true,
        });
        mainWindow?.webContents.send('ai-done', event);
      }
    } catch {
      // ignore malformed event
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    parts.forEach(handlePart);
  }
  if (buffer.trim()) handlePart(buffer);
  // Stream ended without a terminal event (dropped connection): never leave the chat
  // panel stuck in "streaming".
  if (!finished) mainWindow?.webContents.send('ai-done', { stop_reason: 'interrupted' });
});

ipcMain.handle('get-preferences', () => apiRequest('GET', '/api/preferences'));

ipcMain.handle('set-preferences', (_e, partial) =>
  apiRequest('PUT', '/api/preferences', partial)
);

ipcMain.handle('set-api-key', async (_e, key: string) => {
  await keytar.setPassword(KEYTAR_SERVICE, KEYTAR_ACCOUNT, key);
  try {
    await apiRequest('POST', '/api/key', { api_key: key });
  } catch {
    // sidecar may not be ready yet; startup sync will retry
  }
});

ipcMain.handle('has-api-key', async () => {
  const key = await keytar.getPassword(KEYTAR_SERVICE, KEYTAR_ACCOUNT);
  return key !== null && key.length > 0;
});

ipcMain.handle('set-gemini-key', async (_e, key: string) => {
  await keytar.setPassword(KEYTAR_SERVICE, GEMINI_ACCOUNT, key);
  await apiRequest('POST', '/api/key/gemini', { api_key: key });
});

ipcMain.handle('has-gemini-key', async () => {
  const key = await keytar.getPassword(KEYTAR_SERVICE, GEMINI_ACCOUNT);
  return key !== null && key.length > 0;
});

ipcMain.handle('clear-chat', (_e, sessionId: string) =>
  apiRequest('POST', '/api/chat/clear', { session_id: sessionId })
);

ipcMain.handle('get-gemini-models', () => apiRequest('GET', '/api/gemini/models'));
ipcMain.handle('get-ollama-models', () => apiRequest('GET', '/api/ollama/models'));

ipcMain.handle('set-deepgram-key', async (_e, key: string) => {
  await keytar.setPassword(KEYTAR_SERVICE, DEEPGRAM_ACCOUNT, key);
  try {
    await apiRequest('POST', '/api/key/deepgram', { api_key: key });
  } catch {
    // sidecar may not be ready yet; startup sync will retry
  }
});

ipcMain.handle('has-deepgram-key', async () => {
  const key = await keytar.getPassword(KEYTAR_SERVICE, DEEPGRAM_ACCOUNT);
  return key !== null && key.length > 0;
});

ipcMain.handle('get-engine-status', () => apiRequest('GET', '/api/engine/status'));

ipcMain.handle('copy-transcript', async (_e, sessionId: string) => {
  const data = await apiRequest<{ segments: Array<{ speaker: string; wall_clock_time: string; text: string }> }>(
    'GET',
    `/api/session/${sessionId}/transcript`
  );
  const text = data.segments
    .map((s) => {
      const ts = new Date(s.wall_clock_time).toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
      });
      return `[${ts}] ${s.speaker}: ${s.text}`;
    })
    .join('\n');
  clipboard.writeText(text);
});

ipcMain.handle('export-transcript', async (_e, { sessionId, format }: { sessionId: string; format: string }) => {
  const { filePath } = await dialog.showSaveDialog({
    defaultPath: `transcript.${format}`,
    filters: [
      { name: format === 'md' ? 'Markdown' : 'Text', extensions: [format] },
    ],
  });
  if (!filePath) return null;

  const data = await apiRequest<{ segments: Array<{ speaker: string; wall_clock_time: string; text: string }> }>(
    'GET',
    `/api/session/${sessionId}/transcript`
  );

  let content: string;
  if (format === 'md') {
    content = '# Meeting Transcript\n\n';
    content += data.segments
      .map((s) => {
        const ts = new Date(s.wall_clock_time).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        return `**[${ts}] ${s.speaker}**: ${s.text}`;
      })
      .join('\n\n');
  } else {
    content = data.segments
      .map((s) => {
        const ts = new Date(s.wall_clock_time).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        return `[${ts}] ${s.speaker}: ${s.text}`;
      })
      .join('\n');
  }

  require('fs').writeFileSync(filePath, content, 'utf-8');
  return filePath;
});

// Only ever open a folder inside the configured recordings directory: shell.openPath
// launches files too, so an arbitrary path from the renderer would be a code-launch hole.
ipcMain.handle('open-folder', async (_e, folderPath: string) => {
  const { save_path } = await apiRequest<{ save_path: string }>('GET', '/api/preferences');
  const root = path.resolve(save_path);
  const target = path.resolve(String(folderPath));
  if (target !== root && !target.startsWith(root + path.sep)) return 'Path outside recordings folder';
  // The root may not exist until the first session is saved.
  if (target === root) require('fs').mkdirSync(root, { recursive: true });
  return shell.openPath(target);
});

// Custom title bar window controls
ipcMain.handle('window-minimize', () => mainWindow?.minimize());
ipcMain.handle('window-maximize', () => {
  if (!mainWindow || !mainWindow.isMaximizable()) return;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.handle('window-close', () => mainWindow?.close());

ipcMain.handle('set-window-width', (_e, width: number) => {
  if (!mainWindow) return;
  const [, h] = mainWindow.getSize();
  mainWindow.setSize(Math.max(200, Math.round(Number(width))), h);
});

// Compact mode: a fixed 400x800 window with maximize disabled. The previous bounds
// are remembered so leaving compact mode puts the window back where it was.
const COMPACT_SIZE = { width: 400, height: 800 };
let normalBounds: Electron.Rectangle | null = null;

ipcMain.handle('set-compact', (_e, on: boolean) => {
  if (!mainWindow) return;
  if (on) {
    if (!normalBounds) normalBounds = mainWindow.getBounds();
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    mainWindow.setMaximizable(false);
    mainWindow.setSize(COMPACT_SIZE.width, COMPACT_SIZE.height);
  } else {
    mainWindow.setMaximizable(true);
    if (normalBounds) mainWindow.setBounds(normalBounds);
    normalBounds = null;
  }
});

ipcMain.handle('set-opacity', (_e, value: number) => {
  const clamped = Math.min(1, Math.max(0.05, Number(value)));
  mainWindow?.setOpacity(clamped);
  return clamped;
});

ipcMain.handle('set-always-on-top', (_e, value: boolean) => {
  const on = Boolean(value);
  // 'screen-saver' level keeps the window above other apps' normal windows on
  // Windows; the default 'floating' level loses focus to other foreground apps.
  mainWindow?.setAlwaysOnTop(on, 'screen-saver');
  return on;
});

// Apply the frame setting by recreating the window in-place. `frame` is fixed at
// creation, but a full app.relaunch() would kill the Vite dev server in dev and
// leave a blank window — recreating keeps the dev server (and sidecar) alive.
ipcMain.handle('apply-titlebar', (_e, custom: boolean) => {
  const old = mainWindow;
  old?.removeAllListeners('closed'); // don't let the old window null out the new one
  createWindow(Boolean(custom));
  old?.destroy();
});

// ── App lifecycle ─────────────────────────────────────────────────────────────

// Push stored keys into the sidecar's memory so auto-answer (server-initiated,
// no request header) can use them. The Claude key is otherwise sent per-request.
async function syncKeysToSidecar(): Promise<void> {
  try {
    const claude = await keytar.getPassword(KEYTAR_SERVICE, KEYTAR_ACCOUNT);
    if (claude) await apiRequest('POST', '/api/key', { api_key: claude });
    const gemini = await keytar.getPassword(KEYTAR_SERVICE, GEMINI_ACCOUNT);
    if (gemini) await apiRequest('POST', '/api/key/gemini', { api_key: gemini });
    const deepgram = await keytar.getPassword(KEYTAR_SERVICE, DEEPGRAM_ACCOUNT);
    if (deepgram) await apiRequest('POST', '/api/key/deepgram', { api_key: deepgram });
  } catch (err) {
    console.error('Failed to sync keys to sidecar:', err);
  }
}

app.on('ready', async () => {
  try {
    sidecar.onRestarted = () => {
      // A restarted sidecar has no keys and no session. Re-push the keys and tell the
      // renderer, which still believes a recording is running.
      void syncKeysToSidecar();
      mainWindow?.webContents.send('sidecar-error', {
        type: 'error', code: 'sidecar_restarted', recoverable: true,
        message: 'The audio engine restarted. The recording was stopped; start a new one. '
          + 'Text captured so far was saved to your recordings folder.',
      });
    };
    await sidecar.spawn();
    connectWebSocket();
    await syncKeysToSidecar();
    let customTitlebar = false;
    try {
      const prefs = await apiRequest<{ custom_titlebar?: boolean }>('GET', '/api/preferences');
      customTitlebar = Boolean(prefs.custom_titlebar);
    } catch {
      // fall back to the standard OS frame
    }
    createWindow(customTitlebar);
  } catch (err) {
    console.error('Failed to start sidecar:', err);
    app.quit();
  }
});

app.on('before-quit', async (event) => {
  if (quitting) return;
  quitting = true;
  event.preventDefault(); // wait for the sidecar to save a live session, then really quit
  wsConnection?.close();
  try {
    await sidecar.shutdown();
  } finally {
    app.quit();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Vite dev server URL injected by electron-forge
declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string;
declare const MAIN_WINDOW_VITE_NAME: string;
