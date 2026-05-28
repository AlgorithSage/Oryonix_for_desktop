/**
 * useAgentBridge — manages the WebSocket connection to the Python backend.
 *
 * React UI connects directly to ws://127.0.0.1:8765 (Python asyncio server).
 * Tauri Rust spawns the Python process on startup; this store connects once
 * the Python server is ready.
 *
 * Inbound events from Python are routed to useChatStore so the chat UI
 * reflects real agent state (thinking, step updates, task done/fail).
 */
import { create } from 'zustand';
import { useChatStore } from './useChatStore';

const WS_URL = 'ws://127.0.0.1:8765';
const MAX_RETRIES = 60;       // 60 × 2s = 2 minutes before surfacing error state
const RETRY_DELAY_MS = 2000;

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

interface AgentBridgeState {
  status: ConnectionStatus;
  currentStep: string | null;   // latest step description from backend step_update
  // ── Actions ──────────────────────────────────────────────────────────────
  connect: () => void;
  disconnect: () => void;
  /** Returns true if the message was sent, false if not connected. */
  sendTask: (goal: string, sessionId: string) => boolean;
  sendApprovalGrant: (taskId: string) => void;
  sendApprovalDeny: (taskId: string) => void;
  sendHandback: (taskId: string) => void;
  sendForceCloud: (taskId: string) => void;
}

// Module-level WebSocket ref — kept outside Zustand so re-renders never
// accidentally create a second connection.
let _ws: WebSocket | null = null;
let _retries = 0;
let _retryTimer: ReturnType<typeof setTimeout> | null = null;

export const useAgentBridge = create<AgentBridgeState>((set) => ({
  status: 'disconnected',
  currentStep: null,

  connect: () => {
    // Guard: do nothing if already connecting or connected
    if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    _retries = 0;
    if (_retryTimer) {
      clearTimeout(_retryTimer);
      _retryTimer = null;
    }

    const attempt = () => {
      set({ status: 'connecting' });
      const socket = new WebSocket(WS_URL);
      _ws = socket;

      socket.onopen = () => {
        _retries = 0;
        set({ status: 'connected' });
      };

      socket.onclose = () => {
        _ws = null;
        set({ status: 'disconnected', currentStep: null });
        if (_retries < MAX_RETRIES) {
          _retries++;
          _retryTimer = setTimeout(attempt, RETRY_DELAY_MS);
        } else {
          set({ status: 'error' });
        }
      };

      socket.onerror = () => {
        // onclose fires right after onerror — let that handle retry
      };

      socket.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data as string) as Record<string, unknown>;
          handleMessage(msg, set);
        } catch {
          console.error('[AgentBridge] Received non-JSON message:', event.data);
        }
      };
    };

    attempt();
  },

  disconnect: () => {
    if (_retryTimer) {
      clearTimeout(_retryTimer);
      _retryTimer = null;
    }
    if (_ws) {
      _ws.close();
      _ws = null;
    }
    set({ status: 'disconnected', currentStep: null });
  },

  sendTask: (goal: string, sessionId: string): boolean => {
    if (!_ws || _ws.readyState !== WebSocket.OPEN) {
      console.warn('[AgentBridge] Cannot send task — not connected');
      return false;
    }
    _ws.send(JSON.stringify({ type: 'run_task', goal, session_id: sessionId }));
    return true;
  },

  sendApprovalGrant: (taskId: string) => {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: 'approval_grant', task_id: taskId }));
    }
  },

  sendApprovalDeny: (taskId: string) => {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: 'approval_deny', task_id: taskId }));
    }
  },

  sendHandback: (taskId: string) => {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: 'handback', task_id: taskId }));
    }
  },

  sendForceCloud: (taskId: string) => {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: 'force_cloud', task_id: taskId }));
    }
  },
}));

// ── Inbound message handler ───────────────────────────────────────────────────
// Called outside React render — uses .getState() to mutate stores directly.

type SetFn = (partial: Partial<AgentBridgeState>) => void;

function handleMessage(msg: Record<string, unknown>, set: SetFn): void {
  const chat = useChatStore.getState();

  switch (msg.type) {
    case 'state_change': {
      const state = msg.state as string;
      const active = !['FAILED', 'SUCCEEDED', 'IDLE'].includes(state);
      chat.setIsThinking(active);
      if (!active) set({ currentStep: null });
      break;
    }

    case 'step_update': {
      // Surface the live step description in the UI
      const plan = (msg.plan as string | undefined) ?? '';
      const action = (msg.action as string | undefined) ?? '';
      const step = (msg.step as number | undefined) ?? 0;
      const description = plan || action
        ? `Step ${step}: ${action || plan}`
        : `Running step ${step}…`;
      set({ currentStep: description });
      break;
    }

    case 'task_done': {
      chat.setIsThinking(false);
      set({ currentStep: null });
      const text = (msg.message as string | undefined) ??
        (msg.success ? 'Task completed.' : 'Task failed.');
      const sessionId = chat.currentSessionId;
      if (sessionId) {
        chat.addAssistantMessage(sessionId, text);
      }
      break;
    }

    case 'error': {
      chat.setIsThinking(false);
      set({ currentStep: null });
      const errText = (msg.message as string | undefined) ?? 'An unknown error occurred.';
      const sessionId = chat.currentSessionId;
      if (sessionId) {
        chat.addAssistantMessage(sessionId, `Error: ${errText}`);
      }
      break;
    }

    default:
      console.warn('[AgentBridge] Unhandled message type:', msg.type);
  }
}
