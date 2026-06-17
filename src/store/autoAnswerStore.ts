import { create } from 'zustand';

interface AutoAnswerStore {
  question: string;
  answer: string;
  streaming: boolean;
  error: string;
  start: (question: string) => void;
  appendToken: (text: string) => void;
  done: () => void;
  setError: (message: string) => void;
  clear: () => void;
}

export const useAutoAnswerStore = create<AutoAnswerStore>((set) => ({
  question: '',
  answer: '',
  streaming: false,
  error: '',
  start: (question: string) => set({ question, answer: '', error: '', streaming: true }),
  appendToken: (text: string) => set((s) => ({ answer: s.answer + text })),
  done: () => set({ streaming: false }),
  setError: (message: string) => set({ error: message, streaming: false }),
  clear: () => set({ question: '', answer: '', streaming: false, error: '' }),
}));
