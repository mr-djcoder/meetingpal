import { create } from 'zustand';

export interface TranscriptSegment {
  type: string;
  id: string;
  session_id: string;
  speaker: 'You' | 'Them';
  wall_clock_time: string;
  session_offset_seconds: number;
  text: string;
  is_final: boolean;
  confidence: number;
}

interface TranscriptStore {
  sessionId: string | null;
  isRecording: boolean;
  sessionStartedAt: Date | null;
  segments: TranscriptSegment[];
  startSession: (id: string) => void;
  stopSession: () => void;
  addSegment: (segment: TranscriptSegment) => void;
  clearSession: () => void;
}

export const useTranscriptStore = create<TranscriptStore>((set) => ({
  sessionId: null,
  isRecording: false,
  sessionStartedAt: null,
  segments: [],

  startSession: (id: string) =>
    set({
      sessionId: id,
      isRecording: true,
      sessionStartedAt: new Date(),
      segments: [],
    }),

  stopSession: () =>
    set({ isRecording: false }),

  addSegment: (segment: TranscriptSegment) =>
    set((state) => {
      const idx = state.segments.findIndex((s) => s.id === segment.id);
      if (idx === -1) {
        return { segments: [...state.segments, segment] };
      }
      const next = state.segments.slice();
      next[idx] = segment;
      return { segments: next };
    }),

  clearSession: () =>
    set({ sessionId: null, isRecording: false, sessionStartedAt: null, segments: [] }),
}));
