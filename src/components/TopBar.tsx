import { useEffect, useState } from 'react';
import { useRecording } from '../hooks/useRecording';

interface Props {
  onSettingsOpen: () => void;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function TopBar({ onSettingsOpen }: Props) {
  const { isRecording, duration, startRecording, stopRecording } = useRecording();
  const [hasKey, setHasKey] = useState(false);
  const [alwaysOnTop, setAlwaysOnTop] = useState(false);
  const [opacity, setOpacityState] = useState(1);
  const [opacityOpen, setOpacityOpen] = useState(false);

  useEffect(() => {
    window.electronAPI.hasApiKey().then(setHasKey).catch(() => setHasKey(false));
  }, []);

  useEffect(() => {
    window.electronAPI.getPreferences().then((prefs) => {
      setAlwaysOnTop(Boolean(prefs.always_on_top));
      setOpacityState(prefs.window_opacity ?? 1);
    }).catch(() => { /* keep defaults */ });
  }, []);

  const handleToggle = async () => {
    if (isRecording) {
      await stopRecording();
    } else {
      await startRecording();
    }
  };

  const toggleAlwaysOnTop = async () => {
    const next = !alwaysOnTop;
    setAlwaysOnTop(next);
    await window.electronAPI.setAlwaysOnTop(next);
    await window.electronAPI.setPreferences({ always_on_top: next });
  };

  const changeOpacity = async (value: number) => {
    setOpacityState(value);
    const applied = await window.electronAPI.setOpacity(value);
    await window.electronAPI.setPreferences({ window_opacity: applied });
  };

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-700 select-none">
      {/* Logo */}
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 bg-blue-500 rounded-lg flex items-center justify-center text-white font-bold text-sm">
          M
        </div>
        <span className="font-semibold text-white text-sm">MeetingPal</span>
      </div>

      {/* Center controls */}
      <div className="flex items-center gap-4">
        {isRecording && (
          <span className="flex items-center gap-1.5 text-sm text-gray-300">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            {formatDuration(duration)}
          </span>
        )}
        <button
          onClick={handleToggle}
          className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
            isRecording
              ? 'bg-red-600 hover:bg-red-700 text-white'
              : 'bg-blue-600 hover:bg-blue-700 text-white'
          }`}
        >
          {isRecording ? 'Stop Recording' : 'Start Recording'}
        </button>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-3">
        {/* Always-on-top pin */}
        <button
          onClick={toggleAlwaysOnTop}
          title={alwaysOnTop ? 'Unpin (allow other windows on top)' : 'Pin on top of all windows'}
          className={`p-1.5 rounded transition-colors ${
            alwaysOnTop ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5l14 14M9 5h6l-1 5 3 3v2H7v-2l3-3-1-5z" />
          </svg>
        </button>

        {/* Opacity control */}
        <div className="relative">
          <button
            onClick={() => setOpacityOpen((v) => !v)}
            title="Window transparency"
            className="px-2 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
          >
            {Math.round(opacity * 100)}%
          </button>
          {opacityOpen && (
            <div className="absolute right-0 top-8 z-20 bg-gray-800 border border-gray-600 rounded-lg p-3 shadow-lg w-44">
              <label className="text-xs text-gray-400 block mb-2">Transparency</label>
              <input
                type="range"
                min={30}
                max={100}
                step={5}
                value={Math.round(opacity * 100)}
                onChange={(e) => changeOpacity(Number(e.target.value) / 100)}
                className="w-full accent-blue-500"
              />
              <div className="text-xs text-gray-500 mt-1 text-right">{Math.round(opacity * 100)}%</div>
            </div>
          )}
        </div>

        {/* API key status */}
        <div className="flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full ${hasKey ? 'bg-green-500' : 'bg-red-500'}`}
            title={hasKey ? 'API key set' : 'No API key'}
          />
          <span className="text-xs text-gray-400">{hasKey ? 'API key set' : 'No API key'}</span>
        </div>

        {/* Settings */}
        <button
          onClick={onSettingsOpen}
          className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
          title="Settings"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
            />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
