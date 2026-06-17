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

interface InlineAnswer {
  text: string;
  streaming: boolean;
}

interface TranscriptStore {
  sessionId: string | null;
  isRecording: boolean;
  sessionStartedAt: Date | null;
  segments: TranscriptSegment[];
  // AI auto-answers shown inline, keyed by the transcript segment they answer.
  inlineAnswers: Record<string, InlineAnswer>;
  inlineAnchor: string | null;
  startSession: (id: string) => void;
  stopSession: () => void;
  addSegment: (segment: TranscriptSegment) => void;
  clearSession: () => void;
  startInlineAnswer: () => void;
  appendInlineToken: (text: string) => void;
  finishInlineAnswer: () => void;
}

export const useTranscriptStore = create<TranscriptStore>((set, get) => ({
  sessionId: null,
  isRecording: false,
  sessionStartedAt: null,
  segments: [],
  inlineAnswers: {},
  inlineAnchor: null,

  startSession: (id: string) =>
    set({
      sessionId: id,
      isRecording: true,
      sessionStartedAt: new Date(),
      segments: [],
      inlineAnswers: {},
      inlineAnchor: null,
    }),

  stopSession: () =>
    set({ isRecording: false }),

  addSegment: (segment: TranscriptSegment) =>
    set((state) => ({ segments: [...state.segments, segment] })),

  clearSession: () =>
    set({
      sessionId: null,
      isRecording: false,
      sessionStartedAt: null,
      segments: [],
      inlineAnswers: {},
      inlineAnchor: null,
    }),

  // Anchor a new inline answer to the most recent segment (the question that fired it).
  startInlineAnswer: () => {
    const segs = get().segments;
    const anchor = segs.length ? segs[segs.length - 1].id : null;
    if (!anchor) return;
    set((state) => ({
      inlineAnchor: anchor,
      inlineAnswers: { ...state.inlineAnswers, [anchor]: { text: '', streaming: true } },
    }));
  },

  appendInlineToken: (text: string) =>
    set((state) => {
      const anchor = state.inlineAnchor;
      if (!anchor) return {};
      const cur = state.inlineAnswers[anchor] ?? { text: '', streaming: true };
      return { inlineAnswers: { ...state.inlineAnswers, [anchor]: { ...cur, text: cur.text + text } } };
    }),

  finishInlineAnswer: () =>
    set((state) => {
      const anchor = state.inlineAnchor;
      if (!anchor) return {};
      const cur = state.inlineAnswers[anchor];
      if (!cur) return {};
      return { inlineAnswers: { ...state.inlineAnswers, [anchor]: { ...cur, streaming: false } } };
    }),
}));
