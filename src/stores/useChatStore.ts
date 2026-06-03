import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// ── Groq config (injected by Vite from root .env) ───────────────────────────
const GROQ_API_KEY = import.meta.env.VITE_GROQ_API_KEY as string | undefined;
const GROQ_CHAT_MODEL =
  (import.meta.env.VITE_GROQ_CHAT_MODEL as string | undefined) ||
  'llama-3.3-70b-versatile';

const GROQ_MODELS = [
  'llama-3.3-70b-versatile',
  'meta-llama/llama-4-scout-17b-16e-instruct',
];

const OLLAMA_BASE_URL = 'http://localhost:11434';

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
  ollamaModels: string[];
  isOllamaConnected: boolean | null;
  createSession: () => string;
  deleteSession: (id: string) => void;
  selectSession: (id: string) => void;
  togglePinSession: (id: string) => void;
  renameSession: (id: string, title: string) => void;
  sendMessage: (content: string, isAgentMode?: boolean) => Promise<void>;
  editMessage: (messageIndex: number, newContent: string) => Promise<void>;
  setSelectedModel: (model: string) => void;
  fetchModels: () => Promise<void>;
  setIsThinking: (active: boolean) => void;
  addAssistantMessage: (sessionId: string, text: string) => void;
}

// ── OpenAI-compatible streaming helper (works for both Groq and Ollama) ──────
async function streamChatResponse(
  endpoint: string,
  model: string,
  messages: Message[],
  onToken: (token: string) => void,
  apiKey?: string
): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`;

  const response = await fetch(endpoint, {
    method: 'POST',
    headers,
    body: JSON.stringify({ model, messages, stream: true, temperature: 0.7, max_tokens: 1024 }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`API error ${response.status}: ${err}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('Streaming not supported by this browser');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const payload = line.slice(6).trim();
      if (payload === '[DONE]') return;
      try {
        const parsed = JSON.parse(payload);
        const token: string = parsed.choices?.[0]?.delta?.content ?? '';
        if (token) onToken(token);
      } catch {
        // malformed chunk — skip
      }
    }
  }
}

// ── Route: pick endpoint + key based on whether model is local Ollama ─────────
function resolveEndpoint(model: string, ollamaModels: string[]): { endpoint: string; apiKey?: string } {
  if (ollamaModels.includes(model)) {
    return { endpoint: `${OLLAMA_BASE_URL}/v1/chat/completions` };
  }
  if (!GROQ_API_KEY) throw new Error('VITE_GROQ_API_KEY is not set. Add it to the root .env file.');
  return { endpoint: 'https://api.groq.com/openai/v1/chat/completions', apiKey: GROQ_API_KEY };
}

// ── Store ────────────────────────────────────────────────────────────────────
export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: [],
      currentSessionId: null,
      isThinking: false,
      selectedModel: GROQ_CHAT_MODEL,
      availableModels: GROQ_MODELS,
      ollamaModels: [],
      isOllamaConnected: null,

      createSession: () => {
        const state = get();
        const current = state.sessions.find((s) => s.id === state.currentSessionId);
        if (current && current.messages.length === 0) return current.id;

        const empty = state.sessions.find((s) => s.messages.length === 0);
        if (empty) {
          set({ currentSessionId: empty.id });
          return empty.id;
        }

        const id =
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
        const newSession: ChatSession = { id, title: 'New Chat', messages: [], createdAt: Date.now() };
        set((s) => ({ sessions: [newSession, ...s.sessions], currentSessionId: id }));
        return id;
      },

      deleteSession: (id: string) =>
        set((state) => {
          const filtered = state.sessions.filter((s) => s.id !== id);
          const nextId =
            state.currentSessionId === id
              ? filtered.length > 0 ? filtered[0].id : null
              : state.currentSessionId;
          return { sessions: filtered, currentSessionId: nextId };
        }),

      selectSession: (id: string) => set({ currentSessionId: id }),

      togglePinSession: (id: string) =>
        set((state) => ({
          sessions: state.sessions.map((s) => (s.id === id ? { ...s, pinned: !s.pinned } : s)),
        })),

      renameSession: (id: string, title: string) =>
        set((state) => ({
          sessions: state.sessions.map((s) => (s.id === id ? { ...s, title } : s)),
        })),

      setSelectedModel: (model: string) => set({ selectedModel: model }),

      setIsThinking: (active: boolean) => set({ isThinking: active }),

      addAssistantMessage: (sessionId: string, text: string) =>
        set((s) => ({
          sessions: s.sessions.map((sess) =>
            sess.id === sessionId
              ? { ...sess, messages: [...sess.messages, { role: 'assistant' as const, content: text }] }
              : sess
          ),
        })),

      fetchModels: async () => {
        let ollamaModels: string[] = [];
        let isOllamaConnected = false;

        try {
          const res = await fetch(`${OLLAMA_BASE_URL}/api/tags`, { signal: AbortSignal.timeout(3000) });
          if (res.ok) {
            const data = await res.json() as { models: { name: string }[] };
            ollamaModels = (data.models ?? []).map((m) => m.name);
            isOllamaConnected = true;
          }
        } catch {
          // Ollama not running — silently fall through
        }

        const allModels = [...GROQ_MODELS, ...ollamaModels];
        set({ ollamaModels, availableModels: allModels, isOllamaConnected });

        const state = get();
        if (!state.selectedModel || !allModels.includes(state.selectedModel)) {
          set({ selectedModel: GROQ_CHAT_MODEL });
        }
      },

      sendMessage: async (content, isAgentMode = false) => {
        const state = get();
        let activeId = state.currentSessionId ?? state.createSession();

        set((s) => ({
          isThinking: true,
          sessions: s.sessions.map((sess) => {
            if (sess.id !== activeId) return sess;
            const msgs = [...sess.messages, { role: 'user' as const, content }];
            const title = sess.title === 'New Chat'
              ? (content.length > 30 ? content.slice(0, 30) + '...' : content)
              : sess.title;
            return { ...sess, title, messages: msgs };
          }),
        }));

        if (isAgentMode) {
          const { useAgentBridge } = await import('./useAgentBridge');
          const sent = useAgentBridge.getState().sendTask(content, activeId);
          if (!sent) {
            set((s) => ({
              isThinking: false,
              sessions: s.sessions.map((sess) =>
                sess.id !== activeId ? sess : {
                  ...sess,
                  messages: [...sess.messages, {
                    role: 'assistant' as const,
                    content: 'Error: Cannot communicate with the desktop agent backend. Please ensure the agent backend is running.',
                  }],
                }
              ),
            }));
          }
          return;
        }

        const model = get().selectedModel || GROQ_CHAT_MODEL;
        const history = get().sessions.find((s) => s.id === activeId)?.messages ?? [];
        const { endpoint, apiKey } = resolveEndpoint(model, get().ollamaModels);

        set((s) => ({
          isThinking: false,
          sessions: s.sessions.map((sess) =>
            sess.id === activeId
              ? { ...sess, messages: [...sess.messages, { role: 'assistant' as const, content: '' }] }
              : sess
          ),
        }));

        try {
          await streamChatResponse(endpoint, model, history, (token: string) => {
            set((s) => ({
              sessions: s.sessions.map((sess) => {
                if (sess.id !== activeId) return sess;
                const msgs = [...sess.messages];
                const last = msgs[msgs.length - 1];
                if (last?.role === 'assistant') msgs[msgs.length - 1] = { ...last, content: last.content + token };
                return { ...sess, messages: msgs };
              }),
            }));
          }, apiKey);
        } catch (error: unknown) {
          const errorText = `Chat error: ${error instanceof Error ? error.message : String(error)}`;
          set((s) => ({
            isThinking: false,
            sessions: s.sessions.map((sess) => {
              if (sess.id !== activeId) return sess;
              const msgs = [...sess.messages];
              const last = msgs[msgs.length - 1];
              if (last?.role === 'assistant' && last.content === '') {
                msgs[msgs.length - 1] = { ...last, content: errorText };
              } else {
                msgs.push({ role: 'assistant' as const, content: errorText });
              }
              return { ...sess, messages: msgs };
            }),
          }));
        }
      },

      editMessage: async (messageIndex, newContent) => {
        const state = get();
        const activeId = state.currentSessionId;
        if (!activeId) return;

        set((s) => ({
          isThinking: true,
          sessions: s.sessions.map((sess) => {
            if (sess.id !== activeId) return sess;
            const truncated = sess.messages.slice(0, messageIndex + 1);
            truncated[messageIndex] = { ...truncated[messageIndex], content: newContent };
            return { ...sess, messages: truncated };
          }),
        }));

        const model = get().selectedModel || GROQ_CHAT_MODEL;
        const history = get().sessions.find((s) => s.id === activeId)?.messages ?? [];
        const { endpoint, apiKey } = resolveEndpoint(model, get().ollamaModels);

        set((s) => ({
          isThinking: false,
          sessions: s.sessions.map((sess) =>
            sess.id === activeId
              ? { ...sess, messages: [...sess.messages, { role: 'assistant' as const, content: '' }] }
              : sess
          ),
        }));

        try {
          await streamChatResponse(endpoint, model, history, (token: string) => {
            set((s) => ({
              sessions: s.sessions.map((sess) => {
                if (sess.id !== activeId) return sess;
                const msgs = [...sess.messages];
                const last = msgs[msgs.length - 1];
                if (last?.role === 'assistant') msgs[msgs.length - 1] = { ...last, content: last.content + token };
                return { ...sess, messages: msgs };
              }),
            }));
          }, apiKey);
        } catch (error: unknown) {
          const errorText = `Chat error: ${error instanceof Error ? error.message : String(error)}`;
          set((s) => ({
            isThinking: false,
            sessions: s.sessions.map((sess) => {
              if (sess.id !== activeId) return sess;
              const msgs = [...sess.messages];
              const last = msgs[msgs.length - 1];
              if (last?.role === 'assistant' && last.content === '') {
                msgs[msgs.length - 1] = { ...last, content: errorText };
              } else {
                msgs.push({ role: 'assistant' as const, content: errorText });
              }
              return { ...sess, messages: msgs };
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
