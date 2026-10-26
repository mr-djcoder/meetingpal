import { useEffect, useRef, useState } from 'react';
import { useAutoAnswerStore } from '../store/autoAnswerStore';
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
  const removeSegment = useTranscriptStore((s) => s.removeSegment);
  const appendToken = useChatStore((s) => s.appendToken);
  const finalizeAssistantMessage = useChatStore((s) => s.finalizeAssistantMessage);

  const [audioLevels, setAudioLevels] = useState<AudioLevels>({ mic: 0, loopback: 0 });
  const cleanupRefs = useRef<Array<() => void>>([]);

  useEffect(() => {
    const api = window.electronAPI;

    const offTranscript = api.onTranscriptSegment((segment) => {
      addSegment(segment as Parameters<typeof addSegment>[0]);
    });

    const offRemove = api.onTranscriptRemove((m) => removeSegment(m.id));

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
      // The sidecar restarted: its session is gone, so don't keep showing "recording".
      if (error.code === 'sidecar_restarted') {
        useTranscriptStore.getState().stopSession();
        useAutoAnswerStore.getState().clear();
      }
    });

    const aa = useAutoAnswerStore.getState;
    const ts = useTranscriptStore.getState;
    const offAaStart = api.onAutoAnswerStart((m) => {
      aa().start(m.question);
      ts().startInlineAnswer();
    });
    const offAaToken = api.onAutoAnswerToken((m) => {
      aa().appendToken(m.text);
      ts().appendInlineToken(m.text);
    });
    const offAaDone = api.onAutoAnswerDone(() => {
      aa().done();
      ts().finishInlineAnswer();
    });
    const offAaError = api.onAutoAnswerError((m) => aa().setError(m.message));

    cleanupRefs.current = [
      offTranscript, offRemove, offAudio, offToken, offDone, offError,
      offAaStart, offAaToken, offAaDone, offAaError,
    ];
    return () => {
      cleanupRefs.current.forEach((fn) => fn());
    };
  }, [addSegment, removeSegment, appendToken, finalizeAssistantMessage]);

  return audioLevels;
}
