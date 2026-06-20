import { useCallback, useEffect, useRef, useState } from 'react';
import { useAutoAnswerStore } from '../store/autoAnswerStore';
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
    try {
      const result = await window.electronAPI.startSession(options);
      const res = result as { session_id: string };
      startSession(res.session_id);
    } catch (err) {
      // Start failed (e.g. model still loading → 503, or sidecar down). Don't leave
      // the UI half-recording; surface a clear message and stay stopped.
      stopSession();
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(
        /503|model/i.test(msg)
          ? 'Transcription model is still loading — wait a few seconds and try again.'
          : `Could not start recording: ${msg}`
      );
    }
  }, [startSession, stopSession]);

  const stopRecording = useCallback(async () => {
    // Always reset local recording state, even if the sidecar call fails (e.g. the
    // sidecar crashed mid-record) — otherwise the Stop button gets stuck forever.
    try {
      await window.electronAPI.stopSession();
    } finally {
      stopSession();
      useAutoAnswerStore.getState().clear();
    }
  }, [stopSession]);

  return { isRecording, duration, startRecording, stopRecording };
}
