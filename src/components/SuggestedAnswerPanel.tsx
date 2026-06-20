import { useAutoAnswerStore } from '../store/autoAnswerStore';

/**
 * Auto-answer surface: shows the detected question and the streaming answer,
 * rendered literally as `AI: <response>`.
 */
export function SuggestedAnswerPanel() {
  const { question, answer, streaming, error } = useAutoAnswerStore();

  const empty = !question && !answer && !error;

  return (
    <div className="flex flex-col bg-gray-850 border-t border-blue-900/50 px-4 py-3 max-h-56 overflow-y-auto">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-2 h-2 rounded-full bg-blue-400" />
        <span className="text-xs font-semibold text-blue-300">Suggested Answer</span>
        {streaming && <span className="text-xs text-gray-500">streaming…</span>}
      </div>

      {empty && (
        <p className="text-gray-500 text-sm">
          Auto-answers will appear here when the other person asks a question.
        </p>
      )}

      {question && (
        <p className="text-xs text-gray-400 mb-1.5 italic truncate">Q: {question}</p>
      )}

      {error ? (
        <p className="text-red-400 text-sm">{error}</p>
      ) : (
        (answer || streaming) && (
          <p className="text-sm text-gray-100 leading-relaxed whitespace-pre-wrap">
            <span className="text-blue-300 font-semibold">AI:</span> {answer}
            {streaming && (
              <span className="inline-block w-1.5 h-4 ml-0.5 bg-gray-400 animate-pulse align-text-bottom" />
            )}
          </p>
        )
      )}
    </div>
  );
}
