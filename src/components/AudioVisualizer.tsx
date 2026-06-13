import { useEffect, useRef, useState } from 'react';

interface Props {
  micLevel: number;
  loopbackLevel: number;
  isVisible?: boolean;
}

export function AudioVisualizer({ micLevel, loopbackLevel, isVisible = true }: Props) {
  const [smoothMic, setSmoothMic] = useState(0);
  const [smoothLb, setSmoothLb] = useState(0);
  const rafRef = useRef<number>(0);
  const targetMic = useRef(micLevel);
  const targetLb = useRef(loopbackLevel);

  useEffect(() => {
    targetMic.current = micLevel;
    targetLb.current = loopbackLevel;
  }, [micLevel, loopbackLevel]);

  useEffect(() => {
    let currentMic = 0;
    let currentLb = 0;
    const animate = () => {
      currentMic += (targetMic.current - currentMic) * 0.2;
      currentLb += (targetLb.current - currentLb) * 0.2;
      setSmoothMic(currentMic);
      setSmoothLb(currentLb);
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  if (!isVisible) return null;

  const bars = 12;

  return (
    <div className="flex items-end gap-4 px-3 py-2 bg-gray-800 dark:bg-gray-800 rounded-lg">
      <ChannelBars label="Mic" level={smoothMic} bars={bars} color="bg-blue-500" />
      <ChannelBars label="System" level={smoothLb} bars={bars} color="bg-green-500" />
    </div>
  );
}

function ChannelBars({
  label,
  level,
  bars,
  color,
}: {
  label: string;
  level: number;
  bars: number;
  color: string;
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="flex items-end gap-0.5 h-8">
        {Array.from({ length: bars }).map((_, i) => {
          const threshold = i / bars;
          const active = level > threshold;
          const height = `${((i + 1) / bars) * 100}%`;
          return (
            <div
              key={i}
              className={`w-1.5 rounded-sm transition-all duration-75 ${
                active ? color : 'bg-gray-600'
              }`}
              style={{ height }}
            />
          );
        })}
      </div>
      <span className="text-xs text-gray-400">{label}</span>
    </div>
  );
}
