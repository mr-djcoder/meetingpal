import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  // Audio & session
  getDevices: () => ipcRenderer.invoke('get-devices'),
  startSession: (options: unknown) => ipcRenderer.invoke('start-session', options),
  stopSession: () => ipcRenderer.invoke('stop-session'),

  // AI Q&A
  askQuestion: (question: string, model?: string) =>
    ipcRenderer.invoke('ask-question', { question, model }),

  // Preferences
  getPreferences: () => ipcRenderer.invoke('get-preferences'),
  setPreferences: (partial: unknown) => ipcRenderer.invoke('set-preferences', partial),

  // API key management
  setApiKey: (key: string) => ipcRenderer.invoke('set-api-key', key),
  hasApiKey: () => ipcRenderer.invoke('has-api-key'),

  // Auto-answer: Gemini key + model list
  setGeminiKey: (key: string) => ipcRenderer.invoke('set-gemini-key', key),
  hasGeminiKey: () => ipcRenderer.invoke('has-gemini-key'),
  getGeminiModels: () => ipcRenderer.invoke('get-gemini-models'),

  // Real-time listeners — each returns a cleanup function
  onTranscriptSegment: (cb: (segment: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, segment: unknown) => cb(segment);
    ipcRenderer.on('transcript-segment', handler);
    return () => ipcRenderer.removeListener('transcript-segment', handler);
  },
  onAudioLevel: (cb: (frame: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, frame: unknown) => cb(frame);
    ipcRenderer.on('audio-level', handler);
    return () => ipcRenderer.removeListener('audio-level', handler);
  },
  onAiToken: (cb: (token: string) => void) => {
    const handler = (_: Electron.IpcRendererEvent, token: string) => cb(token);
    ipcRenderer.on('ai-token', handler);
    return () => ipcRenderer.removeListener('ai-token', handler);
  },
  onAiDone: (cb: (summary: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, summary: unknown) => cb(summary);
    ipcRenderer.on('ai-done', handler);
    return () => ipcRenderer.removeListener('ai-done', handler);
  },
  onError: (cb: (error: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, error: unknown) => cb(error);
    ipcRenderer.on('sidecar-error', handler);
    return () => ipcRenderer.removeListener('sidecar-error', handler);
  },
  onAutoAnswerStart: (cb: (m: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, m: unknown) => cb(m);
    ipcRenderer.on('auto-answer-start', handler);
    return () => ipcRenderer.removeListener('auto-answer-start', handler);
  },
  onAutoAnswerToken: (cb: (m: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, m: unknown) => cb(m);
    ipcRenderer.on('auto-answer-token', handler);
    return () => ipcRenderer.removeListener('auto-answer-token', handler);
  },
  onAutoAnswerDone: (cb: (m: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, m: unknown) => cb(m);
    ipcRenderer.on('auto-answer-done', handler);
    return () => ipcRenderer.removeListener('auto-answer-done', handler);
  },
  onAutoAnswerError: (cb: (m: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, m: unknown) => cb(m);
    ipcRenderer.on('auto-answer-error', handler);
    return () => ipcRenderer.removeListener('auto-answer-error', handler);
  },

  // Export
  copyTranscript: (sessionId: string) => ipcRenderer.invoke('copy-transcript', sessionId),
  exportTranscript: (sessionId: string, format: string) =>
    ipcRenderer.invoke('export-transcript', { sessionId, format }),
});
