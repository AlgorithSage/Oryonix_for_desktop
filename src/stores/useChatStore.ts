import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// Module-level timer — auto-resets isThinking if backend never responds
let _thinkingTimer: ReturnType<typeof setTimeout> | null = null;
const THINKING_TIMEOUT_MS = 3 * 60 * 1000; // 3 minutes

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
  /** Add user message and set isThinking. Returns the active session id. */
  sendMessage: (content: string) => string;
  /** Called by useAgentBridge when agent state changes. */
  setIsThinking: (value: boolean) => void;
  /** Called by useAgentBridge when Python sends task_done or error. */
  addAssistantMessage: (sessionId: string, content: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: [],
      currentSessionId: null,
      isThinking: false,

      createSession: () => {
        const state = get();

        // Re-use current session if it's already empty
        const currentSession = state.sessions.find((s) => s.id === state.currentSessionId);
        if (currentSession && currentSession.messages.length === 0) {
          return currentSession.id;
        }

        // Re-use any other empty session instead of creating a duplicate
        const existingEmpty = state.sessions.find((s) => s.messages.length === 0);
        if (existingEmpty) {
          set({ currentSessionId: existingEmpty.id });
          return existingEmpty.id;
        }

        // Create a new session
        const id =
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : Math.random().toString(36).substring(2, 15) + Date.now().toString(36);

        const newSession: ChatSession = {
          id,
          title: 'New Chat',
          messages: [],
          createdAt: Date.now(),
        };
        set((s) => ({
          sessions: [newSession, ...s.sessions],
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
          return { sessions: filtered, currentSessionId: nextActiveId };
        });
      },

      selectSession: (id) => {
        set({ currentSessionId: id });
      },

      sendMessage: (content) => {
        const state = get();
        let activeId = state.currentSessionId;

        if (!activeId) {
          activeId = get().createSession();
        }

        set((s) => ({
          isThinking: true,
          sessions: s.sessions.map((sess) => {
            if (sess.id !== activeId) return sess;
            const updatedMessages: Message[] = [
              ...sess.messages,
              { role: 'user' as const, content },
            ];
            const title =
              sess.title === 'New Chat'
                ? content.length > 30
                  ? content.slice(0, 30) + '...'
                  : content
                : sess.title;
            return { ...sess, title, messages: updatedMessages };
          }),
        }));

        // Python backend (via useAgentBridge) takes over from here.
        // addAssistantMessage + setIsThinking(false) are called when
        // the backend sends "task_done" or "error" back over WebSocket.

        return activeId;
      },

      setIsThinking: (value) => {
        if (_thinkingTimer) {
          clearTimeout(_thinkingTimer);
          _thinkingTimer = null;
        }
        if (value) {
          // Auto-unfreeze UI if backend never responds within 3 minutes
          _thinkingTimer = setTimeout(() => {
            set({ isThinking: false });
            _thinkingTimer = null;
            // Add a visible error message to the active session
            const state = useChatStore.getState();
            if (state.currentSessionId) {
              state.addAssistantMessage(
                state.currentSessionId,
                'Error: Agent timed out — no response received within 3 minutes. The backend may have crashed. Please try again.'
              );
            }
          }, THINKING_TIMEOUT_MS);
        }
        set({ isThinking: value });
      },

      addAssistantMessage: (sessionId, content) => {
        set((s) => ({
          sessions: s.sessions.map((sess) => {
            if (sess.id !== sessionId) return sess;
            return {
              ...sess,
              messages: [...sess.messages, { role: 'assistant' as const, content }],
            };
          }),
        }));
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
