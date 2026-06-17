import { app, BrowserWindow, clipboard, dialog, ipcMain, shell } from 'electron';
import * as path from 'path';
import * as keytar from 'keytar';
import { SidecarManager } from './sidecar';

const KEYTAR_SERVICE = 'MeetingPal';
const KEYTAR_ACCOUNT = 'anthropic-api-key';
const GEMINI_ACCOUNT = 'gemini-api-key';
const SIDECAR_PORT = 8001;
const BASE_URL = `http://127.0.0.1:${SIDECAR_PORT}`;

const sidecar = new SidecarManager();
let mainWindow: BrowserWindow | null = null;
let wsConnection: import('ws').WebSocket | null = null;

// ── Window ────────────────────────────────────────────────────────────────────

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#111827',
    titleBarStyle: 'hiddenInset',
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

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── WebSocket connection to sidecar ───────────────────────────────────────────

function connectWebSocket(): void {
  const WebSocket = require('ws');
  const ws = new WebSocket(`ws://127.0.0.1:${SIDECAR_PORT}/ws`);
  wsConnection = ws;

  ws.on('message', (raw: Buffer) => {
    try {
      const msg = JSON.parse(raw.toString());
      if (!mainWindow) return;
      switch (msg.type) {
        case 'transcript_segment':
          mainWindow.webContents.send('transcript-segment', msg);
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
    setTimeout(connectWebSocket, 2000);
  });
  ws.on('error', () => {
    /* reconnect handled by close */
  });
}

// ── API request helper ────────────────────────────────────────────────────────

async function apiRequest<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const apiKey = await keytar.getPassword(KEYTAR_SERVICE, KEYTAR_ACCOUNT);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Sidecar ${method} ${path} → ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── IPC Handlers ─────────────────────────────────────────────────────────────

ipcMain.handle('get-devices', () => apiRequest('GET', '/api/devices'));

ipcMain.handle('start-session', (_e, options) =>
  apiRequest('POST', '/api/session/start', options)
);

ipcMain.handle('stop-session', () => apiRequest('POST', '/api/session/stop', {}));

ipcMain.handle('ask-question', async (_e, { question, model }) => {
  const apiKey = await keytar.getPassword(KEYTAR_SERVICE, KEYTAR_ACCOUNT);
  const preferences = await apiRequest<{ claude_model: string }>('GET', '/api/preferences');
  const claudeModel = model || preferences.claude_model || 'claude-sonnet-4-6';

  // We need session_id from active session — get it from last start response cached in store
  // For simplicity: fetch preferences which has session context from a GET
  // Actually we need a session_id — pass it from the renderer via the question call
  // This is handled: question contains session_id via the ask endpoint
  // Re-route: just forward to /api/ask as SSE and relay tokens
  const res = await fetch(`${BASE_URL}/api/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
    },
    body: JSON.stringify({ question, claude_model: claudeModel }),
  });

  if (!res.ok || !res.body) {
    throw new Error(`Ask failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const dataLine = part.split('\n').find((l) => l.startsWith('data:'));
      const eventLine = part.split('\n').find((l) => l.startsWith('event:'));
      if (!dataLine) continue;
      try {
        const event = JSON.parse(dataLine.slice(5).trim());
        const eventType = eventLine ? eventLine.slice(6).trim() : 'content_delta';
        if (eventType === 'content_delta' && event.text) {
          mainWindow?.webContents.send('ai-token', event.text);
        } else if (eventType === 'message_stop') {
          mainWindow?.webContents.send('ai-done', event);
        } else if (eventType === 'error') {
          mainWindow?.webContents.send('sidecar-error', event);
        }
      } catch {
        // ignore
      }
    }
  }
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

ipcMain.handle('get-gemini-models', () => apiRequest('GET', '/api/gemini/models'));

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

ipcMain.handle('open-folder', (_e, folderPath: string) => shell.openPath(folderPath));

// ── App lifecycle ─────────────────────────────────────────────────────────────

// Push stored keys into the sidecar's memory so auto-answer (server-initiated,
// no request header) can use them. The Claude key is otherwise sent per-request.
async function syncKeysToSidecar(): Promise<void> {
  try {
    const claude = await keytar.getPassword(KEYTAR_SERVICE, KEYTAR_ACCOUNT);
    if (claude) await apiRequest('POST', '/api/key', { api_key: claude });
    const gemini = await keytar.getPassword(KEYTAR_SERVICE, GEMINI_ACCOUNT);
    if (gemini) await apiRequest('POST', '/api/key/gemini', { api_key: gemini });
  } catch (err) {
    console.error('Failed to sync keys to sidecar:', err);
  }
}

app.on('ready', async () => {
  try {
    await sidecar.spawn();
    connectWebSocket();
    await syncKeysToSidecar();
    createWindow();
  } catch (err) {
    console.error('Failed to start sidecar:', err);
    app.quit();
  }
});

app.on('before-quit', async () => {
  wsConnection?.close();
  await sidecar.shutdown();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Vite dev server URL injected by electron-forge
declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string;
declare const MAIN_WINDOW_VITE_NAME: string;
