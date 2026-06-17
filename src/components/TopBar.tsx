import { useEffect, useState } from 'react';
import { useRecording } from '../hooks/useRecording';

interface Props {
  onSettingsOpen: () => void;
  chatVisible: boolean;
  onToggleChat: () => void;
  transcriptVisible: boolean;
  onToggleTranscript: () => void;
  customTitlebar: boolean;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function TopBar({
  onSettingsOpen,
  chatVisible,
  onToggleChat,
  transcriptVisible,
  onToggleTranscript,
  customTitlebar,
}: Props) {
  const { isRecording, duration, startRecording, stopRecording } = useRecording();
  const [autoAnswer, setAutoAnswer] = useState(false);
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    window.electronAPI
      .getPreferences()
      .then((p) => setAutoAnswer(Boolean((p as unknown as { auto_answer_enabled?: boolean }).auto_answer_enabled)))
      .catch(() => { /* default off */ });
  }, []);

  // Collapse labels to icons on a narrow window.
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 450);
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const toggleAutoAnswer = async () => {
    const next = !autoAnswer;
    setAutoAnswer(next);
    await window.electronAPI.setPreferences({ auto_answer_enabled: next } as never);
  };

  const handleToggle = async () => {
    if (isRecording) await stopRecording();
    else await startRecording();
  };

  const recordIcon = isRecording ? (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  ) : (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="12" cy="12" r="7" />
    </svg>
  );

  return (
    <div className="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-700 select-none gap-2">
      {/* Left: record first; logo only when the OS frame is shown */}
      <div className="flex items-center gap-2 min-w-0">
        {!customTitlebar && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-7 h-7 bg-blue-500 rounded-lg flex items-center justify-center text-white font-bold text-sm">
              M
            </div>
            <span className="font-semibold text-white text-sm">MeetingPal</span>
          </div>
        )}

        <button
          onClick={handleToggle}
          title={isRecording ? 'Stop recording' : 'Start recording'}
          className={
            narrow
              ? `w-8 h-8 rounded-full flex items-center justify-center transition-colors ${
                  isRecording ? 'bg-red-600 hover:bg-red-700 text-white' : 'bg-blue-600 hover:bg-blue-700 text-white'
                }`
              : `px-4 py-1.5 rounded-full text-sm font-medium transition-colors flex items-center gap-1.5 ${
                  isRecording ? 'bg-red-600 hover:bg-red-700 text-white' : 'bg-blue-600 hover:bg-blue-700 text-white'
                }`
          }
        >
          {narrow ? recordIcon : isRecording ? 'Stop Recording' : 'Start Recording'}
        </button>

        {isRecording && (
          <span className="flex items-center gap-1.5 text-sm text-gray-300 flex-shrink-0">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            {formatDuration(duration)}
          </span>
        )}
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {/* Auto-answer toggle */}
        <button
          onClick={toggleAutoAnswer}
          title={autoAnswer ? 'Auto-answer ON' : 'Auto-answer OFF'}
          className={
            narrow
              ? `p-1.5 rounded transition-colors ${autoAnswer ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'}`
              : `text-xs px-2 py-1 rounded font-medium transition-colors ${autoAnswer ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'}`
          }
        >
          {narrow ? (
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 2L3 14h7l-1 8 10-12h-7l1-8z" />
            </svg>
          ) : (
            'AI Auto'
          )}
        </button>

        {/* Toggle transcript */}
        <button
          onClick={onToggleTranscript}
          title={transcriptVisible ? 'Hide transcript' : 'Show transcript'}
          className={
            narrow
              ? `p-1.5 rounded transition-colors ${transcriptVisible ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'}`
              : `text-xs px-2 py-1 rounded font-medium transition-colors ${transcriptVisible ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'}`
          }
        >
          {narrow ? (
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h10M4 18h10" />
            </svg>
          ) : (
            'Transcript'
          )}
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
