import { useRef, useEffect } from 'react';
import { useChatStore } from '../../stores/useChatStore';
import { useThemeStore } from '../../stores/useThemeStore';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import { PanelLeft, Sun, Moon } from 'lucide-react';

interface ChatWindowProps {
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

export default function ChatWindow({ sidebarOpen, setSidebarOpen }: ChatWindowProps) {
  const { messages, isThinking } = useChatStore();
  const { theme, toggleTheme } = useThemeStore();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
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
        </div>

        {/* Top Right Actions */}
        <div className="flex items-center gap-2">
          {/* Theme Toggle Icon */}
          <button 
            onClick={(e) => toggleTheme(e)}
            className="text-zinc-500 hover:text-[var(--text-main)] transition-colors cursor-pointer p-1.5 rounded hover:bg-[var(--bg-hover)]"
            title={theme === 'dark' ? "Switch to Light Mode" : "Switch to Dark Mode"}
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
        </div>
      </div>

      {/* Main Chat Scroll Feed */}
      <div className="flex-1 overflow-y-auto" ref={scrollRef}>
        {messages.length === 0 ? (
          /* Empty Welcoming Screen */
          <div className="h-full flex flex-col items-center justify-center max-w-4xl mx-auto w-full px-6 pt-10 pb-28">
            <div className="flex flex-col items-center text-center mb-5">
              <h1 className="text-3xl font-semibold text-[var(--text-main)] tracking-tight">Chat with your model</h1>
            </div>

            {/* Embedded Floating Chat Input Card */}
            <div className="w-full max-w-2xl">
              <ChatInput />
            </div>
          </div>
        ) : (
          /* Scroll Message List Feed */
          <div className="max-w-4xl mx-auto w-full py-6 space-y-6 flex flex-col min-h-full justify-between">
            <div className="space-y-6 flex-1">
              {messages.map((msg, index) => (
                <MessageBubble key={index} message={msg} />
              ))}
            </div>

            {/* Thinking compiling indicator */}
            {isThinking && (
              <div className="flex items-center gap-2 text-[#00c896] font-mono text-[10px] px-4 select-none">
                <span className="animate-pulse">❯</span>
                <span className="animate-pulse tracking-widest font-bold">ORYONIX IS RUNNING MODEL INFERENCE...</span>
              </div>
            )}

            {/* Fixed Chat Input Card at bottom of feed */}
            <div className="w-full pt-4">
              <ChatInput />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
