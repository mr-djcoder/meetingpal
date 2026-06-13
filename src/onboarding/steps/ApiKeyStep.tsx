import { useState } from 'react';

interface Props {
  onNext: () => void;
}

export function ApiKeyStep({ onNext }: Props) {
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSubmit = async () => {
    setError('');
    if (!key.trim()) {
      setError('Please enter your API key.');
      return;
    }
    if (!key.trim().startsWith('sk-ant-')) {
      setError('API key should start with "sk-ant-".');
      return;
    }
    setSaving(true);
    try {
      await window.electronAPI.setApiKey(key.trim());
      setSaved(true);
      setTimeout(onNext, 600);
    } catch {
      setError('Failed to save API key. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Enter your Anthropic API Key</h2>
        <p className="text-gray-400 text-sm">
          MeetingPal uses Claude to answer questions about your meetings. Your key is stored
          securely in Windows Credential Manager and never leaves your machine.
        </p>
      </div>

      <div className="space-y-2">
        <label className="text-sm text-gray-300 font-medium">API Key</label>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="sk-ant-..."
          className="w-full bg-gray-700 text-white rounded-lg px-3 py-2.5 text-sm border border-gray-600 focus:border-blue-500 outline-none"
          autoFocus
        />
        {error && <p className="text-red-400 text-xs">{error}</p>}
        {saved && <p className="text-green-400 text-xs">API key saved securely.</p>}
      </div>

      <p className="text-xs text-gray-500">
        Don't have one?{' '}
        <span className="text-blue-400 cursor-pointer hover:underline" onClick={() => {}}>
          Get one at console.anthropic.com
        </span>
      </p>

      <button
        onClick={handleSubmit}
        disabled={saving || saved}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
      >
        {saving ? 'Saving…' : saved ? 'Saved!' : 'Continue'}
      </button>

      <button
        onClick={onNext}
        disabled={saving || saved}
        className="w-full text-gray-400 hover:text-gray-200 disabled:opacity-60 text-xs py-1 transition-colors"
      >
        Skip — I already have a key configured
      </button>
    </div>
  );
}
