import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
}

interface ChatState {
  sessions: ChatSession[];
  currentSessionId: string | null;
  isThinking: boolean;
  createSession: () => string;
  deleteSession: (id: string) => void;
  selectSession: (id: string) => void;
  sendMessage: (content: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: [],
      currentSessionId: null,
      isThinking: false,

      createSession: () => {
        const state = get();
        
        // 1. If the current active session is already empty, just keep using it
        const currentSession = state.sessions.find((s) => s.id === state.currentSessionId);
        if (currentSession && currentSession.messages.length === 0) {
          return currentSession.id;
        }

        // 2. If there's any other empty session in the list, select it instead of creating a new one
        const existingEmptySession = state.sessions.find((s) => s.messages.length === 0);
        if (existingEmptySession) {
          set({ currentSessionId: existingEmptySession.id });
          return existingEmptySession.id;
        }

        // 3. Otherwise, create a new session
        const id = typeof crypto !== 'undefined' && crypto.randomUUID 
          ? crypto.randomUUID() 
          : Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
        const newSession: ChatSession = {
          id,
          title: 'New Chat',
          messages: [],
          createdAt: Date.now(),
        };
        set((state) => ({
          sessions: [newSession, ...state.sessions],
          currentSessionId: id,
        }));
        return id;
      },

      deleteSession: (id) => {
        set((state) => {
          const filtered = state.sessions.filter((s) => s.id !== id);
          let nextActiveId = state.currentSessionId;
          if (state.currentSessionId === id) {
            nextActiveId = filtered.length > 0 ? filtered[0].id : null;
          }
          return {
            sessions: filtered,
            currentSessionId: nextActiveId,
          };
        });
      },

      selectSession: (id) => {
        set({ currentSessionId: id });
      },

      sendMessage: (content) => {
        const state = get();
        let activeId = state.currentSessionId;

        // If there's no active session, create one first
        if (!activeId) {
          activeId = state.createSession();
        }

        // Add user message to active session and set thinking
        set((s) => ({
          isThinking: true,
          sessions: s.sessions.map((sess) => {
            if (sess.id === activeId) {
              const updatedMessages = [...sess.messages, { role: 'user' as const, content }];
              // If title was still 'New Chat', use the first 30 chars of first message as title
              const title = sess.title === 'New Chat' 
                ? (content.length > 30 ? content.slice(0, 30) + '...' : content) 
                : sess.title;
              return {
                ...sess,
                title,
                messages: updatedMessages,
              };
            }
            return sess;
          }),
        }));

        // Simulate agent response
        setTimeout(() => {
          set((s) => {
            let reply = "I am a local AI assistant. I can see your screen, run files, and execute terminal commands.";
            const contentLower = content.toLowerCase();
            if (contentLower.includes('hello') || contentLower.includes('hi')) {
              reply = "Hello! I am Oryonix, your desktop AI agent. How can I assist you today?";
            } else if (contentLower.includes('chrome') || contentLower.includes('browser')) {
              reply = "Understood. I will prepare a plan to open Google Chrome and perform the requested search.";
            } else if (contentLower.includes('help')) {
              reply = "You can ask me to open programs, edit code files, manage projects, or help write code. Just let me know what you need!";
            }

            return {
              isThinking: false,
              sessions: s.sessions.map((sess) => {
                if (sess.id === activeId) {
                  return {
                    ...sess,
                    messages: [...sess.messages, { role: 'assistant' as const, content: reply }],
                  };
                }
                return sess;
              }),
            };
          });
        }, 1500);
      },
    }),
    {
      name: 'oryonix-chat-sessions',
      partialize: (state) => ({
        sessions: state.sessions,
        currentSessionId: state.currentSessionId,
      }),
    }
  )
);
