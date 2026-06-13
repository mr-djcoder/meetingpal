import { useEffect, useRef, useState } from 'react';
import { useTranscriptStore } from '../store/transcriptStore';

export function TranscriptPanel() {
  const { segments, sessionId, isRecording } = useTranscriptStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [userScrolled, setUserScrolled] = useState(false);
  const [copied, setCopied] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  // Auto-scroll unless user scrolled up
  useEffect(() => {
    if (!userScrolled) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [segments, userScrolled]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const isAtBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
    setUserScrolled(!isAtBottom);
  };

  const handleCopy = async () => {
    if (!sessionId) return;
    await window.electronAPI.copyTranscript(sessionId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExport = async (format: 'txt' | 'md') => {
    if (!sessionId) return;
    setExportOpen(false);
    await window.electronAPI.exportTranscript(sessionId, format);
  };

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
        <span className="text-sm font-medium text-gray-300">Transcript</span>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            disabled={!sessionId}
            className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 transition-colors"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
          <div className="relative">
            <button
              onClick={() => setExportOpen((v) => !v)}
              disabled={!sessionId}
              className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 transition-colors"
            >
              Export
            </button>
            {exportOpen && (
              <div className="absolute right-0 top-7 bg-gray-800 border border-gray-600 rounded shadow-lg z-10">
                <button
                  onClick={() => handleExport('md')}
                  className="block w-full text-left px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700"
                >
                  Markdown (.md)
                </button>
                <button
                  onClick={() => handleExport('txt')}
                  className="block w-full text-left px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700"
                >
                  Plain text (.txt)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Segments */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
      >
        {segments.length === 0 && (
          <p className="text-gray-500 text-sm text-center mt-8">
            {isRecording
              ? 'Listening… transcript will appear here within a few seconds.'
              : 'Start recording to see the live transcript.'}
          </p>
        )}
        {segments.map((seg) => {
          const time = new Date(seg.wall_clock_time).toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
            second: '2-digit',
          });
          const isYou = seg.speaker === 'You';
          return (
            <div key={seg.id} className="flex gap-2 items-start transcript-font">
              <span
                className={`mt-0.5 flex-shrink-0 text-xs font-semibold px-1.5 py-0.5 rounded ${
                  isYou
                    ? 'bg-blue-900 text-blue-300'
                    : 'bg-gray-700 text-gray-300'
                }`}
              >
                {seg.speaker}
              </span>
              <span className="text-xs text-gray-500 flex-shrink-0 mt-0.5">{time}</span>
              <p className="text-gray-100 leading-relaxed">{seg.text}</p>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Scroll-to-bottom indicator */}
      {userScrolled && segments.length > 0 && (
        <button
          onClick={() => {
            setUserScrolled(false);
            bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
          }}
          className="absolute bottom-4 right-4 bg-blue-600 text-white text-xs px-2 py-1 rounded-full shadow"
        >
          ↓ Latest
        </button>
      )}
    </div>
  );
}
