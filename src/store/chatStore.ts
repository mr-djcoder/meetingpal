import { create } from 'zustand';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: Date;
}

interface ChatStore {
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingContent: string;
  addUserMessage: (content: string) => string;
  appendToken: (token: string) => void;
  finalizeAssistantMessage: () => void;
  clearHistory: () => void;
}

let idCounter = 0;
function newId(): string {
  return `msg-${Date.now()}-${++idCounter}`;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isStreaming: false,
  streamingContent: '',

  addUserMessage: (content: string) => {
    const id = newId();
    set((state) => ({
      messages: [
        ...state.messages,
        { id, role: 'user', content, createdAt: new Date() },
      ],
      isStreaming: true,
      streamingContent: '',
    }));
    return id;
  },

  appendToken: (token: string) =>
    set((state) => ({ streamingContent: state.streamingContent + token })),

  finalizeAssistantMessage: () => {
    const { streamingContent } = get();
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: newId(),
          role: 'assistant',
          content: streamingContent,
          createdAt: new Date(),
        },
      ],
      isStreaming: false,
      streamingContent: '',
    }));
  },

  clearHistory: () =>
    set({ messages: [], isStreaming: false, streamingContent: '' }),
}));
