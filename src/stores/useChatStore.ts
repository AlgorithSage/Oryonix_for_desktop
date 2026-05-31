import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { fetch as tauriFetch } from '@tauri-apps/plugin-http';

// Safe fetch helper that works seamlessly both in desktop (Tauri) and standard browser environments
const safeFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const isTauri = typeof window !== 'undefined' && (window as any).__TAURI_INTERNALS__ !== undefined;
  if (isTauri) {
    try {
      return await tauriFetch(input, init);
    } catch (e) {
      console.warn('Tauri fetch failed, falling back to standard fetch:', e);
      return await fetch(input, init);
    }
  } else {
    return await fetch(input, init);
  }
};

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
  pinned?: boolean;
}

interface ChatState {
  sessions: ChatSession[];
  currentSessionId: string | null;
  isThinking: boolean;
  selectedModel: string | null;
  availableModels: string[];
  isOllamaConnected: boolean | null;
  createSession: () => string;
  deleteSession: (id: string) => void;
  selectSession: (id: string) => void;
  togglePinSession: (id: string) => void;
  renameSession: (id: string, title: string) => void;
  sendMessage: (content: string) => Promise<void>;
  editMessage: (messageIndex: number, newContent: string) => Promise<void>;
  setSelectedModel: (model: string) => void;
  fetchModels: () => Promise<void>;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: [],
      currentSessionId: null,
      isThinking: false,
      selectedModel: null,
      availableModels: [],
      isOllamaConnected: null,

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

      togglePinSession: (id) => {
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, pinned: !s.pinned } : s
          ),
        }));
      },

      renameSession: (id, title) => {
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, title } : s
          ),
        }));
      },

      setSelectedModel: (model) => {
        set({ selectedModel: model });
      },

      fetchModels: async () => {
        try {
          const response = await safeFetch('http://localhost:11434/api/tags');
          if (!response.ok) throw new Error('Failed to fetch models');
          const data = await response.json();
          const models = data.models.map((m: any) => m.name);
          
          set({ 
            availableModels: models, 
            isOllamaConnected: true 
          });

          // Set default selected model if not set or not in list anymore
          const state = get();
          if (models.length > 0) {
            if (!state.selectedModel || !models.includes(state.selectedModel)) {
              set({ selectedModel: models[0] });
            }
          }
        } catch (error) {
          console.error('Ollama connection failed:', error);
          set({ 
            availableModels: [], 
            isOllamaConnected: false 
          });
        }
      },

      sendMessage: async (content) => {
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

        try {
          const selectedModel = state.selectedModel || 'qwen2.5vl:3b';
          
          // Get the entire history for the current session
          const currentSession = get().sessions.find((s) => s.id === activeId);
          const historyMessages = currentSession ? currentSession.messages : [];

          const response = await safeFetch('http://localhost:11434/api/chat', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              model: selectedModel,
              messages: historyMessages,
              stream: true,
            }),
          });

          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }

          const reader = response.body?.getReader();
          if (!reader) {
            throw new Error('Readable stream not supported');
          }

          const decoder = new TextDecoder();
          
          // Add empty assistant message that we will stream into
          set((s) => ({
            isThinking: false, // Turn off thinking once stream starts
            sessions: s.sessions.map((sess) => {
              if (sess.id === activeId) {
                return {
                  ...sess,
                  messages: [...sess.messages, { role: 'assistant' as const, content: '' }],
                };
              }
              return sess;
            }),
          }));

          let partialLine = '';
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = (partialLine + chunk).split('\n');
            partialLine = lines.pop() || '';

            for (const line of lines) {
              if (line.trim() === '') continue;
              try {
                const parsed = JSON.parse(line);
                const token = parsed.message?.content || '';
                
                if (token) {
                  set((s) => ({
                    sessions: s.sessions.map((sess) => {
                      if (sess.id === activeId) {
                        const lastMsgIdx = sess.messages.length - 1;
                        const updated = [...sess.messages];
                        if (lastMsgIdx >= 0 && updated[lastMsgIdx].role === 'assistant') {
                          updated[lastMsgIdx] = {
                            ...updated[lastMsgIdx],
                            content: updated[lastMsgIdx].content + token,
                          };
                        }
                        return {
                          ...sess,
                          messages: updated,
                        };
                      }
                      return sess;
                    }),
                  }));
                }
              } catch (e) {
                console.error('Failed to parse streaming JSON line:', e);
              }
            }
          }
        } catch (error: any) {
          console.error('Error calling Ollama:', error);
          set((s) => ({
            isThinking: false,
            sessions: s.sessions.map((sess) => {
              if (sess.id === activeId) {
                const messages = sess.messages;
                const lastMsg = messages[messages.length - 1];
                const errorMessage = `Could not connect to Ollama. Make sure Ollama is running locally at http://localhost:11434 and the model "${state.selectedModel || 'qwen2.5vl:3b'}" is downloaded.\n\nError: ${error.message}`;
                
                if (lastMsg && lastMsg.role === 'assistant' && lastMsg.content === '') {
                  const updated = [...messages];
                  updated[updated.length - 1] = {
                    role: 'assistant',
                    content: errorMessage,
                  };
                  return { ...sess, messages: updated };
                } else {
                  return {
                    ...sess,
                    messages: [...messages, { role: 'assistant' as const, content: errorMessage }],
                  };
                }
              }
              return sess;
            }),
          }));
        }
      },

      editMessage: async (messageIndex, newContent) => {
        const state = get();
        const activeId = state.currentSessionId;
        if (!activeId) return;

        // 1. Update the session: edit the message content and truncate any subsequent messages
        set((s) => ({
          isThinking: true,
          sessions: s.sessions.map((sess) => {
            if (sess.id === activeId) {
              const truncatedMessages = sess.messages.slice(0, messageIndex + 1);
              truncatedMessages[messageIndex] = {
                ...truncatedMessages[messageIndex],
                content: newContent,
              };
              return {
                ...sess,
                messages: truncatedMessages,
              };
            }
            return sess;
          }),
        }));

        // 2. Trigger Ollama stream on the updated history
        try {
          const selectedModel = get().selectedModel || 'qwen2.5vl:3b';
          const currentSession = get().sessions.find((s) => s.id === activeId);
          const historyMessages = currentSession ? currentSession.messages : [];

          const response = await safeFetch('http://localhost:11434/api/chat', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              model: selectedModel,
              messages: historyMessages,
              stream: true,
            }),
          });

          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }

          const reader = response.body?.getReader();
          if (!reader) {
            throw new Error('Readable stream not supported');
          }

          const decoder = new TextDecoder();
          
          // Add empty assistant message that we will stream into
          set((s) => ({
            isThinking: false, // Turn off thinking once stream starts
            sessions: s.sessions.map((sess) => {
              if (sess.id === activeId) {
                return {
                  ...sess,
                  messages: [...sess.messages, { role: 'assistant' as const, content: '' }],
                };
              }
              return sess;
            }),
          }));

          let partialLine = '';
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = (partialLine + chunk).split('\n');
            partialLine = lines.pop() || '';

            for (const line of lines) {
              if (line.trim() === '') continue;
              try {
                const parsed = JSON.parse(line);
                const token = parsed.message?.content || '';
                
                if (token) {
                  set((s) => ({
                    sessions: s.sessions.map((sess) => {
                      if (sess.id === activeId) {
                        const lastMsgIdx = sess.messages.length - 1;
                        const updated = [...sess.messages];
                        if (lastMsgIdx >= 0 && updated[lastMsgIdx].role === 'assistant') {
                          updated[lastMsgIdx] = {
                            ...updated[lastMsgIdx],
                            content: updated[lastMsgIdx].content + token,
                          };
                        }
                        return {
                          ...sess,
                          messages: updated,
                        };
                      }
                      return sess;
                    }),
                  }));
                }
              } catch (e) {
                console.error('Failed to parse streaming JSON line:', e);
              }
            }
          }
        } catch (error: any) {
          console.error('Error calling Ollama:', error);
          set((s) => ({
            isThinking: false,
            sessions: s.sessions.map((sess) => {
              if (sess.id === activeId) {
                const messages = sess.messages;
                const lastMsg = messages[messages.length - 1];
                const errorMessage = `Could not connect to Ollama. Make sure Ollama is running locally at http://localhost:11434 and the model "${get().selectedModel || 'qwen2.5vl:3b'}" is downloaded.\n\nError: ${error.message}`;
                
                if (lastMsg && lastMsg.role === 'assistant' && lastMsg.content === '') {
                  const updated = [...messages];
                  updated[updated.length - 1] = {
                    role: 'assistant',
                    content: errorMessage,
                  };
                  return { ...sess, messages: updated };
                } else {
                  return {
                    ...sess,
                    messages: [...messages, { role: 'assistant' as const, content: errorMessage }],
                  };
                }
              }
              return sess;
            }),
          }));
        }
      },
    }),
    {
      name: 'oryonix-chat-sessions',
      partialize: (state) => ({
        sessions: state.sessions,
        currentSessionId: state.currentSessionId,
        selectedModel: state.selectedModel,
      }),
    }
  )
);
