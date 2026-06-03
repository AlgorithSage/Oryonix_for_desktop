import { useRef, useEffect, useState } from 'react';
import { useChatStore } from '../../stores/useChatStore';
import { useThemeStore } from '../../stores/useThemeStore';
import { useAgentBridge } from '../../stores/useAgentBridge';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import { PanelLeft, Sun, Moon, ChevronDown, SquarePen, Server, Cloud, Check } from 'lucide-react';
import Lenis from 'lenis';
import GridLoader from '../smoothui/grid-loader';

interface ChatWindowProps {
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

export default function ChatWindow({ sidebarOpen, setSidebarOpen }: ChatWindowProps) {
  const { 
    sessions, 
    currentSessionId, 
    isThinking,
    selectedModel,
    availableModels,
    ollamaModels,
    isOllamaConnected,
    fetchModels,
    setSelectedModel,
    createSession
  } = useChatStore();
  const { currentStep } = useAgentBridge();
  const { theme, toggleTheme } = useThemeStore();
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lenisRef = useRef<Lenis | null>(null);
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const messages = currentSession ? currentSession.messages : [];

  // Poll Ollama status on mount and every 5 seconds
  useEffect(() => {
    fetchModels();
    const interval = setInterval(() => {
      fetchModels();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchModels]);

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

  // Auto-scroll to bottom using bottomRef scrollIntoView
  useEffect(() => {
    if (messages.length === 0) return;

    const timer = setTimeout(() => {
      if (bottomRef.current) {
        const isStreaming = messages.length > 0 && messages[messages.length - 1].role === 'assistant';
        // Use smooth animation for general messages, auto (instant) for streaming to keep up with typing speed
        const behavior = isThinking || isStreaming ? 'auto' : 'smooth';
        
        bottomRef.current.scrollIntoView({ 
          behavior,
          block: 'end'
        });
      }
    }, 60);

    return () => clearTimeout(timer);
  }, [messages, isThinking]);

  // Re-pin scroll to bottom when sidebar transitions (open or closed)
  useEffect(() => {
    if (messages.length === 0) return;

    // Trigger scrolls during and after the sidebar transition (e.g., 50ms, 150ms, 300ms)
    // to ensure it stays pinned perfectly to the bottom as the layout resizes
    const timeouts = [50, 150, 300].map((delay) => 
      setTimeout(() => {
        bottomRef.current?.scrollIntoView({ 
          behavior: 'smooth',
          block: 'end'
        });
      }, delay)
    );

    return () => timeouts.forEach(clearTimeout);
  }, [sidebarOpen]);

  // Keyboard shortcut for New Chat (Ctrl+J)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'j') {
        e.preventDefault();
        createSession();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [createSession]);

  // Close model dropdown on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setModelDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--bg-main)] overflow-hidden min-w-0 select-none transition-colors duration-150">
      {/* Top Model Bar */}
      <div className="h-14 px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          {/* Re-open Sidebar Icon */}
          {!sidebarOpen && (
            <button
              onClick={() => setSidebarOpen(true)}
              className="text-zinc-500 hover:text-[var(--text-main)] transition-colors cursor-pointer p-1 rounded-full hover:bg-[var(--bg-hover)] -ml-2"
              title="Expand Sidebar"
            >
              <PanelLeft size={16} />
            </button>
          )}
          {currentSession && messages.length > 0 && (
            <span className="text-xs font-semibold text-zinc-400 font-sans truncate max-w-[150px] animate-fade-in">
              {currentSession.title}
            </span>
          )}
        </div>

        {/* Model Selector and Status */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-[var(--bg-input)] border border-[var(--border-color)] rounded-full px-3 py-1 text-xs select-none">
            {/* Connection Status dot */}
            <span className="relative flex h-2 w-2">
              {isOllamaConnected ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </>
              ) : (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                </>
              )}
            </span>
            
            <span className="font-medium text-zinc-500 dark:text-zinc-400 font-sans">
              {isOllamaConnected ? 'Ollama Online' : 'Ollama Offline'}
            </span>

            {availableModels.length > 0 && (
              <>
                <div className="h-3 w-[1px] bg-[var(--border-color)] mx-1" />
                <div className="relative flex items-center font-sans" ref={dropdownRef}>
                  <button
                    onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
                    className="flex items-center gap-1.5 text-[var(--text-input-active)] font-semibold cursor-pointer outline-none border-none py-0.5 px-1.5 -mx-1.5 rounded-md hover:bg-[var(--bg-hover)] transition-colors select-none font-sans"
                  >
                    {selectedModel && ollamaModels.includes(selectedModel) ? (
                      <Server size={12} className="text-emerald-500 shrink-0" />
                    ) : (
                      <Cloud size={12} className="text-sky-500 shrink-0" />
                    )}
                    <span className="truncate max-w-[150px]">{selectedModel || 'Select Model'}</span>
                    <ChevronDown 
                      size={11} 
                      className={`text-zinc-500 transition-transform duration-200 shrink-0 ${
                        modelDropdownOpen ? 'rotate-180' : ''
                      }`} 
                    />
                  </button>

                  {modelDropdownOpen && (
                    <div className="absolute right-0 top-full mt-2 w-72 bg-[var(--bg-popover)] border border-[var(--border-popover)] rounded-xl shadow-xl py-1.5 z-50 overflow-hidden animate-fade-in max-h-[350px] overflow-y-auto">
                      {/* Cloud Models Section */}
                      {availableModels.filter(m => !ollamaModels.includes(m)).length > 0 && (
                        <div className="px-1 pb-1">
                          <div className="text-[9px] font-bold text-zinc-500 tracking-wider uppercase px-3 py-1.5 select-none">
                            Cloud Models
                          </div>
                          {availableModels
                            .filter(m => !ollamaModels.includes(m))
                            .map((model) => (
                              <button
                                key={model}
                                onClick={() => {
                                  setSelectedModel(model);
                                  setModelDropdownOpen(false);
                                }}
                                className={`w-full text-left px-3 py-2 text-xs font-sans transition-all duration-150 flex items-center justify-between rounded-lg hover:bg-[var(--bg-popover-item-hover)] group ${
                                  selectedModel === model
                                    ? 'text-[var(--text-popover-item-hover)] font-semibold bg-[var(--bg-popover-item-hover)]'
                                    : 'text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)]'
                                }`}
                              >
                                <div className="flex items-center gap-2 truncate">
                                  <Cloud size={13} className="text-sky-500 shrink-0" />
                                  <span className="truncate">{model}</span>
                                </div>
                                {selectedModel === model && (
                                  <Check size={13} className="text-emerald-500 shrink-0" />
                                )}
                              </button>
                            ))}
                        </div>
                      )}

                      {/* Divider if both sections exist */}
                      {availableModels.filter(m => !ollamaModels.includes(m)).length > 0 && 
                       availableModels.filter(m => ollamaModels.includes(m)).length > 0 && (
                        <div className="h-[1px] bg-[var(--border-color)] my-1 mx-2" />
                      )}

                      {/* Local Models Section */}
                      {availableModels.filter(m => ollamaModels.includes(m)).length > 0 && (
                        <div className="px-1 pt-1">
                          <div className="text-[9px] font-bold text-zinc-500 tracking-wider uppercase px-3 py-1.5 select-none">
                            Local Models (Ollama)
                          </div>
                          {availableModels
                            .filter(m => ollamaModels.includes(m))
                            .map((model) => (
                              <button
                                key={model}
                                onClick={() => {
                                  setSelectedModel(model);
                                  setModelDropdownOpen(false);
                                }}
                                className={`w-full text-left px-3 py-2 text-xs font-sans transition-all duration-150 flex items-center justify-between rounded-lg hover:bg-[var(--bg-popover-item-hover)] group ${
                                  selectedModel === model
                                    ? 'text-[var(--text-popover-item-hover)] font-semibold bg-[var(--bg-popover-item-hover)]'
                                    : 'text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)]'
                                }`}
                              >
                                <div className="flex items-center gap-2 truncate">
                                  <Server size={13} className="text-emerald-500 shrink-0" />
                                  <span className="truncate">{model}</span>
                                </div>
                                {selectedModel === model && (
                                  <Check size={13} className="text-emerald-500 shrink-0" />
                                )}
                              </button>
                            ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* New Chat Button (only visible when in an active conversation) */}
          {messages.length > 0 && (
            <button
              onClick={() => createSession()}
              className="text-zinc-500 hover:text-[var(--text-main)] transition-colors cursor-pointer p-1.5 rounded-full hover:bg-[var(--bg-hover)] animate-fade-in"
              title="New Chat (Ctrl+J)"
            >
              <SquarePen size={17} />
            </button>
          )}

          {/* Theme Toggle Icon */}
          <button 
            onClick={(e) => toggleTheme(e)}
            className="text-zinc-500 hover:text-[var(--text-main)] transition-colors cursor-pointer p-1.5 rounded-full hover:bg-[var(--bg-hover)]"
            title={theme === 'dark' ? "Switch to Light Mode" : "Switch to Dark Mode"}
          >
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </div>

      {messages.length === 0 ? (
        /* Main Chat Scroll Feed - Empty State */
        <div className="flex-1 overflow-y-auto" ref={scrollRef}>
          <div className="h-full flex flex-col items-center justify-center max-w-4xl mx-auto w-full px-6 pt-10 pb-44">
            <div className="flex flex-col items-center text-center mb-5">
              <h1 className="text-3xl font-semibold text-[var(--text-main)] tracking-tight">Chat with Oryonix</h1> 
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
            <div className="max-w-[860px] mx-auto w-full pt-6 pb-8 px-4 space-y-6 flex flex-col">
              <div className="space-y-6 flex-1">
                {messages.map((msg, index) => (
                  <MessageBubble key={index} message={msg} index={index} />
                ))}
              </div>

              {/* Thinking compiling indicator */}
              {isThinking && (
                <div className="flex items-start gap-3 select-none animate-fade-in w-full">
                  {/* Left loader area - perfectly matches the w-7 h-7 badge size and centering */}
                  <div className="w-7 h-7 flex items-center justify-center shrink-0">
                    <GridLoader 
                      size={16} 
                      gap={1.5} 
                      color="white" 
                      mode="stagger" 
                      pattern={[
                        [1, 1, 1],
                        [1, 1, 1],
                        [1, 1, 1]
                      ]} 
                      speed="normal"
                      rounded
                    />
                  </div>
                  
                  {/* Right text area - perfectly matches the py-1 content alignment */}
                  <div className="flex flex-col py-1 flex-1">
                    <span className="text-[#F56C13] font-mono text-[9px] tracking-widest font-bold uppercase animate-pulse">
                      {currentStep ? 'Agent Executing' : 'Running Inference'}
                    </span>
                    <span className="text-zinc-300 text-[11px] font-sans mt-0.5 font-medium leading-relaxed">
                      {currentStep || 'Oryonix is formulating response...'}
                    </span>
                  </div>
                </div>
              )}

              {/* Bulletproof anchor for auto-scrolling */}
              <div ref={bottomRef} className="h-2 w-full shrink-0" />
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
