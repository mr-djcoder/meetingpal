import { useCallback, useEffect, useState } from 'react';

interface AudioDevice {
  index: number;
  name: string;
  device_type: 'microphone' | 'loopback';
  is_default: boolean;
}

interface Props {
  onNext: () => void;
  onBack: () => void;
}

export function AudioSetupStep({ onNext, onBack }: Props) {
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadDevices = useCallback(async () => {
    setLoading(true);
    setError('');
    // The sidecar may still be loading the Whisper model when this step mounts,
    // so getDevices can fail transiently — retry with backoff instead of latching.
    for (let attempt = 0; attempt < 10; attempt++) {
      try {
        const res = await window.electronAPI.getDevices();
        setDevices(res.devices as AudioDevice[]);
        setLoading(false);
        return;
      } catch {
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
    setError('Failed to enumerate audio devices.');
    setLoading(false);
  }, []);

  useEffect(() => {
    loadDevices();
  }, [loadDevices]);

  const defaultMic = devices.find((d) => d.device_type === 'microphone' && d.is_default);
  const defaultLoopback = devices.find((d) => d.device_type === 'loopback' && d.is_default);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Audio Device Setup</h2>
        <p className="text-gray-400 text-sm">
          MeetingPal captures your microphone and system audio simultaneously. Verify the
          detected devices below.
        </p>
      </div>

      {loading && <p className="text-gray-400 text-sm">Detecting audio devices…</p>}
      {error && (
        <div className="flex items-center gap-3">
          <p className="text-red-400 text-sm">{error}</p>
          <button
            onClick={loadDevices}
            className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && (
        <div className="space-y-3">
          <DeviceCard
            icon="🎤"
            label="Microphone (Your voice)"
            name={defaultMic?.name ?? 'No default microphone detected'}
            ok={!!defaultMic}
          />
          <DeviceCard
            icon="🔊"
            label="System Audio (Meeting participants)"
            name={defaultLoopback?.name ?? 'No WASAPI loopback device found'}
            ok={!!defaultLoopback}
            warning={
              !defaultLoopback
                ? 'No loopback device found. You may need to update your audio drivers or enable "Stereo Mix" in Windows Sound settings.'
                : undefined
            }
          />
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
          disabled={loading}
          className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
        >
          Looks good, continue
        </button>
      </div>
    </div>
  );
}

function DeviceCard({
  icon,
  label,
  name,
  ok,
  warning,
}: {
  icon: string;
  label: string;
  name: string;
  ok: boolean;
  warning?: string;
}) {
  return (
    <div
      className={`rounded-lg p-3 border ${
        ok ? 'border-gray-600 bg-gray-800' : 'border-yellow-700 bg-yellow-900/20'
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span>{icon}</span>
        <span className="text-xs text-gray-400 font-medium">{label}</span>
        {ok ? (
          <span className="ml-auto text-green-400 text-xs">Detected</span>
        ) : (
          <span className="ml-auto text-yellow-400 text-xs">Not found</span>
        )}
      </div>
      <p className="text-sm text-white truncate">{name}</p>
      {warning && <p className="text-xs text-yellow-400 mt-1.5">{warning}</p>}
    </div>
  );
}
