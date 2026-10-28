import { create } from 'zustand';

interface AutoAnswerStore {
  question: string;
  answer: string;
  streaming: boolean;
  error: string;
  // When the box is hidden nothing is written to it, so showing it again starts clean.
  panelVisible: boolean;
  setPanelVisible: (visible: boolean) => void;
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
  panelVisible: true,
  setPanelVisible: (visible: boolean) =>
    set(visible ? { panelVisible: true } : { panelVisible: false, question: '', answer: '', streaming: false, error: '' }),
  start: (question: string) =>
    set((s) => (s.panelVisible ? { question, answer: '', error: '', streaming: true } : {})),
  appendToken: (text: string) =>
    set((s) => (s.panelVisible ? { answer: s.answer + text } : {})),
  done: () => set((s) => (s.panelVisible ? { streaming: false } : {})),
  setError: (message: string) =>
    set((s) => (s.panelVisible ? { error: message, streaming: false } : {})),
  clear: () => set({ question: '', answer: '', streaming: false, error: '' }),
}));
