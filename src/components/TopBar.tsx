import { useEffect, useState } from 'react';
import { useRecording } from '../hooks/useRecording';

interface Props {
  onSettingsOpen: () => void;
  chatVisible: boolean;
  onToggleChat: () => void;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function TopBar({ onSettingsOpen, chatVisible, onToggleChat }: Props) {
  const { isRecording, duration, startRecording, stopRecording } = useRecording();
  const [autoAnswer, setAutoAnswer] = useState(false);

  useEffect(() => {
    window.electronAPI
      .getPreferences()
      .then((p) => setAutoAnswer(Boolean((p as unknown as { auto_answer_enabled?: boolean }).auto_answer_enabled)))
      .catch(() => { /* default off */ });
  }, []);

  const toggleAutoAnswer = async () => {
    const next = !autoAnswer;
    setAutoAnswer(next);
    await window.electronAPI.setPreferences({ auto_answer_enabled: next } as never);
  };

  const handleToggle = async () => {
    if (isRecording) {
      await stopRecording();
    } else {
      await startRecording();
    }
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
        {/* Auto-answer quick toggle */}
        <button
          onClick={toggleAutoAnswer}
          title={autoAnswer ? 'Auto-answer ON' : 'Auto-answer OFF'}
          className={`text-xs px-2 py-1 rounded font-medium transition-colors ${
            autoAnswer ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          AI Auto
        </button>

        {/* Collapse AI chat sidebar */}
        <button
          onClick={onToggleChat}
          title={chatVisible ? 'Hide AI panel' : 'Show AI panel'}
          className={`p-1.5 rounded transition-colors ${
            chatVisible ? 'text-gray-400 hover:text-white hover:bg-gray-700' : 'bg-blue-600 text-white'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5h16v14H4z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5v14" />
          </svg>
        </button>

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
