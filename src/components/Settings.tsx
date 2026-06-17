import { useEffect, useState } from 'react';

interface AudioDevice {
  index: number;
  name: string;
  device_type: 'microphone' | 'loopback';
  is_default: boolean;
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
}

const CLAUDE_MODELS = [
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 — fast' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
];

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export function Settings({ isOpen, onClose }: Props) {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [draft, setDraft] = useState<Partial<UserPreferences>>({});
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [apiKey, setApiKey] = useState('');
  const [keySaved, setKeySaved] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [geminiKey, setGeminiKey] = useState('');
  const [geminiKeySaved, setGeminiKeySaved] = useState(false);
  const [hasGemini, setHasGemini] = useState(false);
  const [geminiModels, setGeminiModels] = useState<string[]>([]);

  useEffect(() => {
    if (!isOpen) return;
    Promise.all([
      window.electronAPI.getPreferences(),
      window.electronAPI.getDevices(),
    ]).then(([p, d]) => {
      setPrefs(p as UserPreferences);
      setDraft({});
      setDevices((d as { devices: AudioDevice[] }).devices);
    });
    window.electronAPI.hasApiKey().then(setHasKey).catch(() => setHasKey(false));
    window.electronAPI.hasGeminiKey().then(setHasGemini).catch(() => setHasGemini(false));
    window.electronAPI
      .getGeminiModels()
      .then((r) => setGeminiModels(r.models))
      .catch(() => setGeminiModels([]));
  }, [isOpen]);

  if (!isOpen || !prefs) return null;

  const merged = { ...prefs, ...draft };

  const update = (partial: Partial<UserPreferences>) =>
    setDraft((d) => ({ ...d, ...partial }));

  const handleSave = async () => {
    setSaving(true);
    try {
      await window.electronAPI.setPreferences(draft);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const handleSaveKey = async () => {
    if (!apiKey.trim()) return;
    await window.electronAPI.setApiKey(apiKey.trim());
    setApiKey('');
    setHasKey(true);
    setKeySaved(true);
    setTimeout(() => setKeySaved(false), 2000);
  };

  const handleSaveGeminiKey = async () => {
    if (!geminiKey.trim()) return;
    await window.electronAPI.setGeminiKey(geminiKey.trim());
    setGeminiKey('');
    setHasGemini(true);
    setGeminiKeySaved(true);
    setTimeout(() => setGeminiKeySaved(false), 2000);
    window.electronAPI.getGeminiModels().then((r) => setGeminiModels(r.models)).catch(() => {});
  };

  const mics = devices.filter((d) => d.device_type === 'microphone');
  const loopbacks = devices.filter((d) => d.device_type === 'loopback');

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-gray-900 rounded-2xl border border-gray-700 shadow-2xl max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-gray-900 border-b border-gray-700 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">
            ×
          </button>
        </div>

        <div className="px-6 py-5 space-y-6">
          {/* API Key */}
          <Section title="API Key">
            <div className="flex items-center gap-1.5 mb-2">
              <div className={`w-2 h-2 rounded-full ${hasKey ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-xs text-gray-400">{hasKey ? 'API key set' : 'No API key'}</span>
            </div>
            <div className="flex gap-2">
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-ant-… (leave blank to keep current)"
                className="flex-1 bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
              />
              <button
                onClick={handleSaveKey}
                disabled={!apiKey.trim()}
                className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm rounded-lg transition-colors"
              >
                {keySaved ? 'Saved!' : 'Update'}
              </button>
            </div>
          </Section>

          {/* Whisper Model */}
          <Section title="Transcription Model">
            <RadioGroup
              value={merged.whisper_model}
              onChange={(v) => update({ whisper_model: v })}
              options={[
                { value: 'base.en', label: 'Base (fast, less accurate)' },
                { value: 'small.en', label: 'Small (balanced)' },
                { value: 'medium.en', label: 'Medium (slower, more accurate)' },
              ]}
            />
          </Section>

          {/* Claude Model */}
          <Section title="AI Model">
            <RadioGroup
              value={merged.claude_model}
              onChange={(v) => update({ claude_model: v })}
              options={[
                { value: 'claude-sonnet-4-6', label: 'Claude Sonnet (fast, recommended)' },
                { value: 'claude-opus-4-6', label: 'Claude Opus (most capable, slower)' },
              ]}
            />
          </Section>

          {/* Auto-Answer */}
          <Section title="Auto-Answer (suggested replies)">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-300">Enable auto-answer</span>
                <button
                  onClick={() => update({ auto_answer_enabled: !merged.auto_answer_enabled })}
                  className={`relative inline-flex h-5 w-9 rounded-full transition-colors ${
                    merged.auto_answer_enabled ? 'bg-blue-600' : 'bg-gray-600'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                      merged.auto_answer_enabled ? 'translate-x-4' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Prompt</label>
                <textarea
                  value={merged.auto_answer_prompt}
                  onChange={(e) => update({ auto_answer_prompt: e.target.value })}
                  rows={3}
                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none resize-none"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Provider</label>
                <select
                  value={merged.auto_answer_provider}
                  onChange={(e) => {
                    const p = e.target.value;
                    const model =
                      p === 'gemini' ? geminiModels[0] ?? 'gemini-3.5-flash' : 'claude-haiku-4-5-20251001';
                    update({ auto_answer_provider: p, auto_answer_model: model });
                  }}
                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
                >
                  <option value="claude">Claude (Anthropic)</option>
                  <option value="gemini">Gemini (Google)</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Model</label>
                <select
                  value={merged.auto_answer_model}
                  onChange={(e) => update({ auto_answer_model: e.target.value })}
                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
                >
                  {merged.auto_answer_provider === 'gemini'
                    ? geminiModels.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))
                    : CLAUDE_MODELS.map((m) => (
                        <option key={m.value} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                </select>
              </div>
              {merged.auto_answer_provider === 'gemini' && (
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">
                    Gemini API Key{' '}
                    {hasGemini ? (
                      <span className="text-green-400">(set)</span>
                    ) : (
                      <span className="text-red-400">(not set)</span>
                    )}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={geminiKey}
                      onChange={(e) => setGeminiKey(e.target.value)}
                      placeholder="AIza… (transcript is sent to Google when Gemini is selected)"
                      className="flex-1 bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
                    />
                    <button
                      onClick={handleSaveGeminiKey}
                      disabled={!geminiKey.trim()}
                      className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm rounded-lg transition-colors"
                    >
                      {geminiKeySaved ? 'Saved!' : 'Save'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </Section>

          {/* Audio Devices */}
          <Section title="Audio Devices">
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Microphone</label>
                <select
                  value={merged.mic_device_index ?? ''}
                  onChange={(e) =>
                    update({ mic_device_index: e.target.value ? Number(e.target.value) : null })
                  }
                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
                >
                  <option value="">System default</option>
                  {mics.map((d) => (
                    <option key={d.index} value={d.index}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1 block">System Audio (WASAPI Loopback)</label>
                <select
                  value={merged.loopback_device_index ?? ''}
                  onChange={(e) =>
                    update({ loopback_device_index: e.target.value ? Number(e.target.value) : null })
                  }
                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
                >
                  <option value="">System default</option>
                  {loopbacks.map((d) => (
                    <option key={d.index} value={d.index}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </Section>

          {/* Theme */}
          <Section title="Appearance">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-300">Theme</span>
                <button
                  onClick={() =>
                    update({ theme: merged.theme === 'dark' ? 'light' : 'dark' })
                  }
                  className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-sm text-gray-200 rounded-lg transition-colors"
                >
                  {merged.theme === 'dark' ? 'Dark' : 'Light'}
                </button>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-gray-300">Font Size</span>
                  <span className="text-sm text-gray-400">{merged.font_size}px</span>
                </div>
                <input
                  type="range"
                  min={10}
                  max={24}
                  value={merged.font_size}
                  onChange={(e) => update({ font_size: Number(e.target.value) })}
                  className="w-full accent-blue-500"
                />
              </div>
            </div>
          </Section>

          {/* Save */}
          <Section title="Transcript Saving">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-300">Auto-save on Stop Recording</span>
                <button
                  onClick={() => update({ auto_save: !merged.auto_save })}
                  className={`relative inline-flex h-5 w-9 rounded-full transition-colors ${
                    merged.auto_save ? 'bg-blue-600' : 'bg-gray-600'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                      merged.auto_save ? 'translate-x-4' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Save Location</label>
                <input
                  value={merged.save_path}
                  onChange={(e) => update({ save_path: e.target.value })}
                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
                />
              </div>
            </div>
          </Section>
        </div>

        <div className="sticky bottom-0 bg-gray-900 border-t border-gray-700 px-6 py-4 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 bg-gray-700 hover:bg-gray-600 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || Object.keys(draft).length === 0}
            className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  );
}

function RadioGroup({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="space-y-2">
      {options.map((opt) => (
        <label key={opt.value} className="flex items-center gap-2.5 cursor-pointer">
          <input
            type="radio"
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
            className="accent-blue-500"
          />
          <span className="text-sm text-gray-300">{opt.label}</span>
        </label>
      ))}
    </div>
  );
}
