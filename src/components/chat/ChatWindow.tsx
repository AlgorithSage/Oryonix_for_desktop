import { useRef, useEffect } from 'react';
import { useChatStore } from '../../stores/useChatStore';
import { useThemeStore } from '../../stores/useThemeStore';
import { useAgentBridge } from '../../stores/useAgentBridge';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import { PanelLeft, Sun, Moon } from 'lucide-react';
import Lenis from 'lenis';

interface ChatWindowProps {
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

export default function ChatWindow({ sidebarOpen, setSidebarOpen }: ChatWindowProps) {
  const { sessions, currentSessionId, isThinking } = useChatStore();
  const { theme, toggleTheme } = useThemeStore();
  const { status, currentStep } = useAgentBridge();
  const scrollRef = useRef<HTMLDivElement>(null);
  const lenisRef = useRef<Lenis | null>(null);

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const messages = currentSession ? currentSession.messages : [];

  // Initialize Lenis on the scroll container
  useEffect(() => {
    const scrollContainer = scrollRef.current;
    if (!scrollContainer) return;

    const lenis = new Lenis({
      wrapper: scrollContainer,
      content: scrollContainer.firstElementChild as HTMLElement,
      duration: 1.0,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
    });

    lenisRef.current = lenis;

    let rafId: number;
    function raf(time: number) {
      lenis.raf(time);
      rafId = requestAnimationFrame(raf);
    }
    rafId = requestAnimationFrame(raf);

    return () => {
      lenis.destroy();
      lenisRef.current = null;
      cancelAnimationFrame(rafId);
    };
  }, [messages.length === 0]); // Re-initialize if switching between empty state and message list

  // Auto-scroll to bottom using Lenis
  useEffect(() => {
    if (lenisRef.current) {
      lenisRef.current.scrollTo('bottom', { duration: 0.6 });
    } else {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [messages]);

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--bg-main)] overflow-hidden min-w-0 select-none transition-colors duration-150">
      {/* Top Model Bar */}
      <div className="h-14 px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          {/* Re-open Sidebar Icon */}
          {!sidebarOpen && (
            <button
              onClick={() => setSidebarOpen(true)}
              className="text-zinc-500 hover:text-[var(--text-main)] transition-colors cursor-pointer p-1 rounded hover:bg-[var(--bg-hover)] -ml-2"
              title="Expand Sidebar"
            >
              <PanelLeft size={16} />
            </button>
          )}
          {currentSession && messages.length > 0 && (
            <span className="text-xs font-semibold text-zinc-400 font-sans truncate max-w-[250px] animate-fade-in">
              {currentSession.title}
            </span>
          )}
        </div>

        {/* Top Right Actions */}
        <div className="flex items-center gap-3">
          {/* Backend connection status dot */}
          <div className="flex items-center gap-1.5" title={`Backend: ${status}`}>
            <span className={`w-2 h-2 rounded-full shrink-0 ${
              status === 'connected'    ? 'bg-[#00c896]' :
              status === 'connecting'   ? 'bg-yellow-400 animate-pulse' :
              status === 'error'        ? 'bg-red-500' :
                                          'bg-zinc-600'
            }`} />
            <span className="text-[10px] font-mono text-zinc-500 hidden sm:block">
              {status === 'connected'  ? 'connected' :
               status === 'connecting' ? 'connecting…' :
               status === 'error'      ? 'offline' : 'disconnected'}
            </span>
          </div>

          {/* Theme Toggle Icon */}
          <button
            onClick={(e) => toggleTheme(e)}
            className="text-zinc-500 hover:text-(--text-main) transition-colors cursor-pointer p-1.5 rounded hover:bg-(--bg-hover)"
            title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
        </div>
      </div>

      {messages.length === 0 ? (
        /* Main Chat Scroll Feed - Empty State */
        <div className="flex-1 overflow-y-auto" ref={scrollRef}>
          <div className="h-full flex flex-col items-center justify-center max-w-4xl mx-auto w-full px-6 pt-10 pb-28">
            <div className="flex flex-col items-center text-center mb-5">
              <h1 className="text-3xl font-semibold text-[var(--text-main)] tracking-tight">Chat with your model</h1>
            </div>

            {/* Embedded Floating Chat Input Card */}
            <div className="w-full max-w-2xl">
              <ChatInput />
            </div>
          </div>
        </div>
      ) : (
        /* Stacked Layout - Scrollable Message Feed + Fixed Bottom Chat Input (No overlap/clipping) */
        <div className="flex-1 flex flex-col h-full overflow-hidden">
          {/* Scrollable Message Feed */}
          <div className="flex-1 overflow-y-auto" ref={scrollRef}>
            <div className="max-w-[860px] mx-auto w-full pt-6 pb-1 px-4 space-y-6 flex flex-col">
              <div className="space-y-6 flex-1">
                {messages.map((msg, index) => (
                  <MessageBubble key={index} message={msg} />
                ))}
              </div>

              {/* Thinking / live step indicator */}
              {isThinking && (
                <div className="flex items-center gap-2 text-[#00c896] font-mono text-[10px] px-6 py-2 select-none animate-fade-in">
                  <span className="animate-pulse">❯</span>
                  <span className="animate-pulse tracking-widest font-bold truncate max-w-[600px]">
                    {currentStep ?? 'ORYONIX IS RUNNING MODEL INFERENCE...'}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Fixed Chat Input Card at bottom of screen */}
          <div className="w-full max-w-4xl mx-auto pb-4 pt-0 px-4 shrink-0">
            <ChatInput />
          </div>
        </div>
      )}
    </div>
  );
}
