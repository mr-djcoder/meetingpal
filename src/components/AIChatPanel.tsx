import { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { useChatStore } from '../store/chatStore';
import { useTranscriptStore } from '../store/transcriptStore';

const SUGGESTED_PROMPTS = [
  'Summarize so far',
  'What are the action items?',
  'Catch me up — I zoned out',
  'What was just decided?',
  'Draft a follow-up email',
];

export function AIChatPanel() {
  const { messages, isStreaming, streamingContent, addUserMessage } = useChatStore();
  const { sessionId } = useTranscriptStore();
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleSend = async (text?: string) => {
    const question = (text ?? input).trim();
    if (!question || isStreaming || !sessionId) return;
    setInput('');
    setError(null);
    addUserMessage(question);
    try {
      await window.electronAPI.askQuestion(question);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleChipClick = (prompt: string) => {
    handleSend(prompt);
  };

  return (
    <div className="flex flex-col h-full bg-gray-850 border-l border-gray-700">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-700">
        <span className="text-sm font-semibold text-white">MeetingPal AI</span>
        <span className="text-xs px-1.5 py-0.5 bg-blue-900 text-blue-300 rounded font-medium">
          {sessionId ? 'Active' : 'Idle'}
        </span>
      </div>

      {/* Messages */}
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center mt-8 space-y-2">
            <p className="text-gray-400 text-sm">Ask me anything about the meeting.</p>
            <p className="text-gray-600 text-xs">Ctrl+Enter to send</p>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-br-sm'
                  : 'bg-gray-700 text-gray-100 rounded-bl-sm'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {/* Streaming assistant message */}
        {isStreaming && streamingContent && (
          <div className="flex justify-start">
            <div className="max-w-[85%] bg-gray-700 text-gray-100 rounded-xl rounded-bl-sm px-3 py-2 text-sm leading-relaxed">
              {streamingContent}
              <span className="inline-block w-1.5 h-4 ml-0.5 bg-gray-400 animate-pulse align-text-bottom" />
            </div>
          </div>
        )}

        {isStreaming && !streamingContent && (
          <div className="flex justify-start">
            <div className="bg-gray-700 rounded-xl rounded-bl-sm px-4 py-2">
              <div className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-900/50 text-red-300 text-xs px-3 py-2 rounded">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Suggested prompts */}
      {!isStreaming && messages.length === 0 && sessionId && (
        <div className="px-3 pb-1 flex flex-wrap gap-1.5">
          {SUGGESTED_PROMPTS.map((p) => (
            <button
              key={p}
              onClick={() => handleChipClick(p)}
              className="text-xs px-2 py-1 rounded-full bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors"
            >
              {p}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="px-3 pb-3 pt-1">
        <div className="flex items-end gap-2 bg-gray-700 rounded-xl px-3 py-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={sessionId ? 'Ask about the meeting… (Ctrl+Enter)' : 'Start a recording first'}
            disabled={!sessionId || isStreaming}
            rows={1}
            className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 resize-none outline-none max-h-32 overflow-y-auto disabled:opacity-50"
            style={{ lineHeight: '1.5' }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || isStreaming || !sessionId}
            className="flex-shrink-0 w-7 h-7 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg flex items-center justify-center transition-colors"
          >
            <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
