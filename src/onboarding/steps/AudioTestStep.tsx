import { useEffect, useRef, useState } from 'react';
import { AudioVisualizer } from '../../components/AudioVisualizer';
import { useWebSocket } from '../../hooks/useWebSocket';

interface Props {
  onNext: () => void;
  onBack: () => void;
}

export function AudioTestStep({ onNext, onBack }: Props) {
  const [testing, setTesting] = useState(false);
  const [micSeen, setMicSeen] = useState(false);
  const [loopbackSeen, setLoopbackSeen] = useState(false);
  const audioLevels = useWebSocket();
  const sessionStarted = useRef(false);

  useEffect(() => {
    if (audioLevels.mic > 0.05) setMicSeen(true);
    if (audioLevels.loopback > 0.05) setLoopbackSeen(true);
  }, [audioLevels]);

  const startTest = async () => {
    if (sessionStarted.current) return;
    sessionStarted.current = true;
    setTesting(true);
    try {
      await window.electronAPI.startSession({ duration_limit_seconds: 10 });
    } catch {
      setTesting(false);
      sessionStarted.current = false;
    }
  };

  const handleNext = async () => {
    if (testing) {
      try {
        await window.electronAPI.stopSession();
      } catch {
        // ignore
      }
    }
    onNext();
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Audio Test</h2>
        <p className="text-gray-400 text-sm">
          Let's verify both audio channels are working. Click Start Test, then speak and play
          something through your speakers.
        </p>
      </div>

      {!testing ? (
        <button
          onClick={startTest}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
        >
          Start Audio Test (10s)
        </button>
      ) : (
        <div className="space-y-4">
          <AudioVisualizer micLevel={audioLevels.mic} loopbackLevel={audioLevels.loopback} />
          <div className="flex gap-4">
            <ChannelStatus label="Microphone" detected={micSeen} />
            <ChannelStatus label="System Audio" detected={loopbackSeen} />
          </div>
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
          onClick={handleNext}
          className="flex-1 bg-blue-600 hover:bg-blue-700 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
        >
          {testing ? 'Continue' : 'Skip Test'}
        </button>
      </div>
    </div>
  );
}

function ChannelStatus({ label, detected }: { label: string; detected: boolean }) {
  return (
    <div
      className={`flex-1 rounded-lg p-3 border text-sm ${
        detected
          ? 'border-green-700 bg-green-900/20 text-green-300'
          : 'border-gray-600 bg-gray-800 text-gray-400'
      }`}
    >
      <span className="mr-2">{detected ? '✓' : '○'}</span>
      {label}
    </div>
  );
}
