import type { TranscriptSegment } from '../store/transcriptStore';

interface AudioDevice {
  index: number;
  name: string;
  device_type: 'microphone' | 'loopback';
  channels: number;
  default_sample_rate: number;
  is_default: boolean;
}

interface StartSessionOptions {
  mic_device_index?: number | null;
  loopback_device_index?: number | null;
  whisper_model?: string;
  duration_limit_seconds?: number | null;
}

interface SessionInfo {
  session_id: string;
  started_at: string;
  status: string;
}

interface SessionSummary {
  session_id: string;
  stopped_at: string;
  duration_seconds: number;
  segment_count: number;
  save_path: string | null;
}

interface UserPreferences {
  whisper_model: string;
  claude_model: string;
  mic_device_index: number | null;
  loopback_device_index: number | null;
  auto_save: boolean;
  save_path: string;
  font_size: number;
  theme: 'dark' | 'light';
  onboarding_completed: boolean;
  auto_answer_enabled: boolean;
  auto_answer_prompt: string;
  auto_answer_provider: string;
  auto_answer_model: string;
  chat_panel_visible: boolean;
  custom_titlebar: boolean;
}

interface AudioLevelFrame {
  type: 'audio_level';
  mic_level: number;
  loopback_level: number;
  timestamp_ms: number;
}

interface SidecarError {
  type: 'error';
  code: string;
  message: string;
  recoverable: boolean;
}

interface AiMessageSummary {
  stop_reason: string;
  input_tokens: number;
  output_tokens: number;
}

type ClaudeModel = 'claude-sonnet-4-6' | 'claude-opus-4-6';

interface ElectronAPI {
  getDevices(): Promise<{ devices: AudioDevice[] }>;
  startSession(options: StartSessionOptions): Promise<SessionInfo>;
  stopSession(): Promise<SessionSummary>;
  askQuestion(question: string, model?: ClaudeModel): Promise<void>;
  getPreferences(): Promise<UserPreferences>;
  setPreferences(partial: Partial<UserPreferences>): Promise<UserPreferences>;
  setApiKey(key: string): Promise<void>;
  hasApiKey(): Promise<boolean>;
  setGeminiKey(key: string): Promise<void>;
  hasGeminiKey(): Promise<boolean>;
  getGeminiModels(): Promise<{ models: string[] }>;
  onTranscriptSegment(cb: (segment: TranscriptSegment) => void): () => void;
  onAudioLevel(cb: (frame: AudioLevelFrame) => void): () => void;
  onAiToken(cb: (token: string) => void): () => void;
  onAiDone(cb: (summary: AiMessageSummary) => void): () => void;
  onError(cb: (error: SidecarError) => void): () => void;
  onAutoAnswerStart(cb: (m: { question: string }) => void): () => void;
  onAutoAnswerToken(cb: (m: { text: string }) => void): () => void;
  onAutoAnswerDone(cb: (m: unknown) => void): () => void;
  onAutoAnswerError(cb: (m: { message: string }) => void): () => void;
  windowMinimize(): Promise<void>;
  windowMaximize(): Promise<void>;
  windowClose(): Promise<void>;
  applyTitlebar(custom: boolean): Promise<void>;
  copyTranscript(sessionId: string): Promise<void>;
  exportTranscript(sessionId: string, format: 'txt' | 'md'): Promise<string | null>;
}

declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}

export {};
