import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranscriptStore } from '../store/transcriptStore';

export interface RecordingState {
  isRecording: boolean;
  duration: number;
  startRecording: (options?: StartSessionOptions) => Promise<void>;
  stopRecording: () => Promise<void>;
}

interface StartSessionOptions {
  mic_device_index?: number | null;
  loopback_device_index?: number | null;
  whisper_model?: string;
  duration_limit_seconds?: number | null;
}

export function useRecording(): RecordingState {
  const { isRecording, sessionStartedAt, startSession, stopSession } = useTranscriptStore();
  const [duration, setDuration] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isRecording && sessionStartedAt) {
      intervalRef.current = setInterval(() => {
        setDuration(Math.floor((Date.now() - sessionStartedAt.getTime()) / 1000));
      }, 1000);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (!isRecording) setDuration(0);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isRecording, sessionStartedAt]);

  const startRecording = useCallback(async (options: StartSessionOptions = {}) => {
    const result = await window.electronAPI.startSession(options);
    const res = result as { session_id: string };
    startSession(res.session_id);
  }, [startSession]);

  const stopRecording = useCallback(async () => {
    await window.electronAPI.stopSession();
    stopSession();
  }, [stopSession]);

  return { isRecording, duration, startRecording, stopRecording };
}
