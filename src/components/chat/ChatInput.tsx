import { useState, KeyboardEvent, useRef, useCallback, useEffect } from 'react';
import { Mic, Bot, MessageSquare } from 'lucide-react';
import { useChatStore } from '../../stores/useChatStore';

export default function ChatInput() {
  const [input, setInput] = useState('');
  const [isGrown, setIsGrown] = useState(false);
  const [isAgentMode, setIsAgentMode] = useState(true); // default to Agent Mode because Oryonix is a CUA app!
  const { sendMessage, isThinking } = useChatStore();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Lock to prevent shrink-back from triggering on the same render cycle as a grow
  const grownLockRef = useRef(false);

  // Auto-focus the input box when AI finishes responding (or on page load)
  useEffect(() => {
    if (!isThinking) {
      const timer = setTimeout(() => {
        textareaRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [isThinking]);

  const resizeTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const sh = textarea.scrollHeight;
    textarea.style.height = `${sh}px`;
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setInput(val);

    // Resize first
    resizeTextarea();

    const textarea = textareaRef.current;
    if (!textarea) return;
    const sh = textarea.scrollHeight;

    if (!isGrown) {
      // Pill → Box: grow when text wraps to 2+ lines
      if (sh > 38) {
        setIsGrown(true);
        grownLockRef.current = true;
        // Release lock after a short delay so the next onChange can evaluate shrink
        setTimeout(() => { grownLockRef.current = false; }, 150);
      }
    } else if (!grownLockRef.current) {
      // Box → Pill: only shrink back when text is completely cleared
      if (val.length === 0) {
        setIsGrown(false);
      }
    }
  };

  const handleSend = () => {
    if (input.trim() && !isThinking) {
      sendMessage(input.trim(), isAgentMode);
      setInput('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
      setIsGrown(false);
      grownLockRef.current = false;
    }
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const modeToggle = (
    <button
      onClick={() => setIsAgentMode(!isAgentMode)}
      className={`h-8 px-3 rounded-full flex items-center gap-1.5 transition-all text-xs font-semibold select-none cursor-pointer border active:scale-95 shrink-0
        ${isAgentMode
          ? 'bg-purple-950/20 border-purple-500/30 text-purple-300 hover:bg-purple-950/40 hover:border-purple-500/50 shadow-[0_0_10px_rgba(168,85,247,0.15)]'
          : 'bg-zinc-800/20 border-zinc-700/30 text-zinc-400 hover:bg-zinc-800/40 hover:border-zinc-700/50'}`}
      title="Toggle between CUA Desktop Agent and General Chat Assistant"
    >
      {isAgentMode ? (
        <>
          <Bot size={13} className="stroke-[2.2] text-[#c084fc]" />
          <span>Agent Mode</span>
        </>
      ) : (
        <>
          <MessageSquare size={13} className="stroke-[2.2] text-zinc-450" />
          <span>Chat Mode</span>
        </>
      )}
    </button>
  );

  /* ── Pill shape: single-row layout ── */
  if (!isGrown) {
    return (
      <div className="w-full select-none font-sans px-2 pt-0 pb-2 shrink-0">
        <div className="max-w-4xl mx-auto bg-[var(--bg-input)] border border-[var(--border-color)] shadow-lg flex flex-row items-center rounded-full py-3 pl-6 pr-3 transition-all duration-300 ease-in-out">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder={isAgentMode ? "Ask the agent to control your computer..." : "Ask anything..."}
            rows={1}
            className="flex-1 bg-transparent pl-0.5 pr-2 outline-none placeholder-zinc-500 resize-none overflow-hidden"
            style={{ height: '24px', lineHeight: '24px', padding: 0, fontFamily: "'Space Grotesk', sans-serif", fontSize: '16px', fontWeight: 400, color: 'var(--text-main)' }}
            disabled={isThinking}
          />
          {/* Inline actions */}
          <div className="flex items-center gap-1.5 shrink-0 ml-auto pl-2">
            {modeToggle}
            <button className="w-9 h-9 !p-0 flex items-center justify-center text-zinc-500 hover:text-[var(--text-main)] cursor-pointer transition-colors rounded-full hover:!bg-[var(--bg-hover)] !bg-transparent !border-none !shadow-none" title="Voice Input">
              <Mic size={18} className="stroke-[1.8]" />
            </button>
            <button
              onClick={handleSend}
              disabled={!input.trim() || isThinking}
              className={`w-9 h-9 !p-0 flex items-center justify-center cursor-pointer transition-all active:scale-95 !bg-transparent !border-none !shadow-none
                ${(!input.trim() || isThinking)
                  ? 'text-zinc-700 opacity-40 cursor-not-allowed'
                  : 'text-[#F56C13] hover:text-[#e05e0d]'}`}
              title="Send Message"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="12" fill="currentColor" stroke="none" />
                <path d="m16 12-4-4-4 4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M12 16V8" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    );
  }

  /* ── Box shape: multi-row layout ── */
  return (
    <div className="w-full select-none font-sans px-4 pt-0 pb-2 shrink-0">
      <div className="max-w-4xl mx-auto bg-[var(--bg-input)] border border-[var(--border-color)] shadow-md flex flex-col rounded-2xl p-3 gap-2 transition-all duration-300 ease-in-out">
        {/* Textarea takes full width — no wrapper row, no gap */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={isAgentMode ? "Ask the agent to control your computer..." : "Ask anything..."}
          rows={2}
          className="w-full bg-transparent px-1 pt-0.5 pb-1.5 outline-none placeholder-zinc-400 resize-none max-h-40 min-h-[4rem] overflow-y-auto animate-fade-in"
          style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '17px', lineHeight: '24px', fontWeight: 400, color: 'var(--text-main)' }}
          disabled={isThinking}
        />

        {/* Bottom actions row */}
        <div className="flex items-center justify-between px-0.5 animate-fade-in">
          {modeToggle}
          <div className="flex items-center gap-1">
            <button className="w-9 h-9 !p-0 flex items-center justify-center text-zinc-400 hover:text-[var(--text-main)] cursor-pointer transition-colors rounded-full hover:!bg-[var(--bg-hover)] !bg-transparent !border-none !shadow-none" title="Voice Input">
              <Mic size={18} className="stroke-[1.8]" />
            </button>
            <button
              onClick={handleSend}
              disabled={!input.trim() || isThinking}
              className={`w-9 h-9 !p-0 flex items-center justify-center cursor-pointer transition-all active:scale-95 !bg-transparent !border-none !shadow-none
                ${(!input.trim() || isThinking)
                  ? 'text-zinc-700 opacity-40 cursor-not-allowed'
                  : 'text-[#F56C13] hover:text-[#e05e0d]'}`}
              title="Send Message"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="12" fill="currentColor" stroke="none" />
                <path d="m16 12-4-4-4 4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M12 16V8" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
