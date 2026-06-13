import { useEffect, useRef, useState } from 'react';
import { useChatStore } from '../store/chatStore';
import { useTranscriptStore } from '../store/transcriptStore';

interface AudioLevelFrame {
  type: 'audio_level';
  mic_level: number;
  loopback_level: number;
  timestamp_ms: number;
}

export interface AudioLevels {
  mic: number;
  loopback: number;
}

export function useWebSocket(): AudioLevels {
  const addSegment = useTranscriptStore((s) => s.addSegment);
  const appendToken = useChatStore((s) => s.appendToken);
  const finalizeAssistantMessage = useChatStore((s) => s.finalizeAssistantMessage);

  const [audioLevels, setAudioLevels] = useState<AudioLevels>({ mic: 0, loopback: 0 });
  const cleanupRefs = useRef<Array<() => void>>([]);

  useEffect(() => {
    const api = window.electronAPI;

    const offTranscript = api.onTranscriptSegment((segment) => {
      addSegment(segment as Parameters<typeof addSegment>[0]);
    });

    const offAudio = api.onAudioLevel((frame) => {
      const f = frame as AudioLevelFrame;
      setAudioLevels({ mic: f.mic_level, loopback: f.loopback_level });
    });

    const offToken = api.onAiToken((token) => {
      appendToken(token as string);
    });

    const offDone = api.onAiDone(() => {
      finalizeAssistantMessage();
    });

    const offError = api.onError((error) => {
      console.error('[sidecar error]', error);
    });

    cleanupRefs.current = [offTranscript, offAudio, offToken, offDone, offError];
    return () => {
      cleanupRefs.current.forEach((fn) => fn());
    };
  }, [addSegment, appendToken, finalizeAssistantMessage]);

  return audioLevels;
}
