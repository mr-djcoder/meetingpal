import { useState } from 'react';

interface Props {
  onComplete: () => void;
  onBack: () => void;
}

export function ReadyStep({ onComplete, onBack }: Props) {
  const [loading, setLoading] = useState(false);

  const handleStart = async () => {
    setLoading(true);
    try {
      await window.electronAPI.setPreferences({ onboarding_completed: true });
      onComplete();
    } catch {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 text-center">
      <div className="text-5xl">🎉</div>
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">You're ready!</h2>
        <p className="text-gray-400 text-sm">
          MeetingPal is set up and ready to help you in your next meeting.
        </p>
      </div>

      <ul className="text-left space-y-2">
        {[
          'Real-time transcription with speaker labels',
          'AI Q&A powered by Claude — ask anything about the meeting',
          'Auto-save transcripts to your Documents folder',
          'Works with any meeting app: Zoom, Teams, Meet, and more',
        ].map((item) => (
          <li key={item} className="flex items-start gap-2 text-sm text-gray-300">
            <span className="text-green-400 flex-shrink-0 mt-0.5">✓</span>
            {item}
          </li>
        ))}
      </ul>

      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="flex-1 bg-gray-700 hover:bg-gray-600 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
        >
          Back
        </button>
        <button
          onClick={handleStart}
          disabled={loading}
          className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
        >
          {loading ? 'Starting…' : 'Start Using MeetingPal'}
        </button>
      </div>
    </div>
  );
}
