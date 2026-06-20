import { useEffect, useState } from 'react';

const MOCK_SEGMENTS = [
  { speaker: 'You', text: "Let's get started. I wanted to discuss the Q2 roadmap today." },
  { speaker: 'Them', text: 'Sure. I think the main priorities should be the API redesign and performance work.' },
  { speaker: 'You', text: "Agreed. The API redesign is blocking three teams. Let's target end of April." },
  { speaker: 'Them', text: 'That works. I can have a draft spec ready by Friday for review.' },
  { speaker: 'You', text: 'Perfect. On performance — do we have baseline metrics yet?' },
  { speaker: 'Them', text: 'Not yet but Sarah is running benchmarks this week. We should have numbers by Thursday.' },
];

const MOCK_AI = "Based on the discussion: (1) API redesign is the top Q2 priority, targeting end of April. (2) Draft spec due Friday. (3) Performance baseline metrics expected Thursday from Sarah. Action items: spec review Friday, follow up on benchmarks Thursday.";

interface Props {
  onNext: () => void;
  onBack: () => void;
}

export function DemoStep({ onNext, onBack }: Props) {
  const [visibleSegments, setVisibleSegments] = useState<typeof MOCK_SEGMENTS>([]);
  const [aiText, setAiText] = useState('');
  const [showAi, setShowAi] = useState(false);

  useEffect(() => {
    let i = 0;
    const interval = setInterval(() => {
      if (i < MOCK_SEGMENTS.length) {
        const seg = MOCK_SEGMENTS[i];
        setVisibleSegments((v) => [...v, seg]);
        i++;
      } else {
        clearInterval(interval);
        setTimeout(() => setShowAi(true), 500);
      }
    }, 150);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!showAi) return;
    let i = 0;
    const interval = setInterval(() => {
      if (i < MOCK_AI.length) {
        setAiText(MOCK_AI.slice(0, i + 1));
        i++;
      } else {
        clearInterval(interval);
      }
    }, 18);
    return () => clearInterval(interval);
  }, [showAi]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">This is what MeetingPal looks like</h2>
        <p className="text-gray-400 text-sm">
          Watch the transcript appear in real time, then see how MeetingPal answers questions.
        </p>
      </div>

      {/* Mock transcript */}
      <div className="bg-gray-800 rounded-lg p-3 max-h-36 overflow-y-auto space-y-1.5">
        {visibleSegments.map((seg, i) => (
          <div key={i} className="flex gap-2 items-start text-sm">
            <span
              className={`flex-shrink-0 text-xs font-semibold px-1.5 py-0.5 rounded mt-0.5 ${
                seg.speaker === 'You' ? 'bg-blue-900 text-blue-300' : 'bg-gray-700 text-gray-300'
              }`}
            >
              {seg.speaker}
            </span>
            <span className="text-gray-200">{seg.text}</span>
          </div>
        ))}
      </div>

      {/* Mock AI response */}
      {showAi && (
        <div className="bg-gray-700 rounded-lg p-3">
          <p className="text-xs text-gray-400 mb-1 font-semibold">MeetingPal AI</p>
          <p className="text-sm text-gray-100 leading-relaxed">
            {aiText}
            {aiText.length < MOCK_AI.length && (
              <span className="inline-block w-1.5 h-4 ml-0.5 bg-gray-400 animate-pulse align-text-bottom" />
            )}
          </p>
        </div>
      )}

      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="flex-1 bg-gray-700 hover:bg-gray-600 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
        >
          Back
        </button>
        <button
          onClick={onNext}
          className="flex-1 bg-blue-600 hover:bg-blue-700 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
        >
          Looks great!
        </button>
      </div>
    </div>
  );
}
