import { useState, KeyboardEvent, useRef, useCallback } from 'react';
import { Mic } from 'lucide-react';
import { useChatStore } from '../../stores/useChatStore';

export default function ChatInput() {
  const [input, setInput] = useState('');
  const [isGrown, setIsGrown] = useState(false);
  const { sendMessage, isThinking } = useChatStore();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Lock to prevent shrink-back from triggering on the same render cycle as a grow
  const grownLockRef = useRef(false);

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
      sendMessage(input.trim());
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

  /* ── Pill shape: single-row layout ── */
  if (!isGrown) {
    return (
      <div className="w-full select-none font-sans px-4 py-2 shrink-0">
        <div className="max-w-2xl mx-auto bg-[var(--bg-input)] shadow-md flex flex-row items-center rounded-[28px] py-2.5 pl-5 pr-2 transition-all duration-300 ease-in-out">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything..."
            rows={1}
            className="flex-1 bg-transparent pl-1 pr-3 outline-none placeholder-zinc-400 resize-none overflow-hidden"
            style={{ height: '24px', lineHeight: '24px', padding: 0, fontFamily: "'Space Grotesk', sans-serif", fontSize: '17px', fontWeight: 400, color: 'var(--text-main)' }}
            disabled={isThinking}
          />
          {/* Inline actions */}
          <div className="flex items-center gap-1 shrink-0 ml-auto pl-2">
            <button className="w-9 h-9 !p-0 flex items-center justify-center text-zinc-400 hover:text-[var(--text-main)] cursor-pointer transition-colors rounded hover:!bg-[var(--bg-hover)] !bg-transparent !border-none !shadow-none" title="Voice Input">
              <Mic size={18} className="stroke-[1.8]" />
            </button>
            <button
              onClick={handleSend}
              disabled={!input.trim() || isThinking}
              className={`w-9 h-9 !p-0 flex items-center justify-center cursor-pointer transition-all active:scale-95 !bg-transparent !border-none !shadow-none
                ${(!input.trim() || isThinking)
                  ? 'text-zinc-700 opacity-40 cursor-not-allowed'
                  : 'text-[#00c896] hover:text-[#00b084]'}`}
              title="Send Message"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" fill="currentColor" stroke="none" />
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
    <div className="w-full select-none font-sans px-4 py-2 shrink-0">
      <div className="max-w-2xl mx-auto bg-[var(--bg-input)] shadow-md flex flex-col rounded-2xl p-3 gap-2 transition-all duration-300 ease-in-out">
        {/* Textarea takes full width — no wrapper row, no gap */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything..."
          rows={2}
          className="w-full bg-transparent px-1 pt-0.5 pb-1.5 outline-none placeholder-zinc-400 resize-none max-h-40 min-h-[4rem] overflow-y-auto animate-fade-in"
          style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '17px', lineHeight: '24px', fontWeight: 400, color: 'var(--text-main)' }}
          disabled={isThinking}
        />

        {/* Bottom actions row */}
        <div className="flex items-center justify-end px-0.5 animate-fade-in">
          <div className="flex items-center gap-1">
            <button className="w-9 h-9 !p-0 flex items-center justify-center text-zinc-400 hover:text-[var(--text-main)] cursor-pointer transition-colors rounded hover:!bg-[var(--bg-hover)] !bg-transparent !border-none !shadow-none" title="Voice Input">
              <Mic size={18} className="stroke-[1.8]" />
            </button>
            <button
              onClick={handleSend}
              disabled={!input.trim() || isThinking}
              className={`w-9 h-9 !p-0 flex items-center justify-center cursor-pointer transition-all active:scale-95 !bg-transparent !border-none !shadow-none
                ${(!input.trim() || isThinking)
                  ? 'text-zinc-700 opacity-40 cursor-not-allowed'
                  : 'text-[#00c896] hover:text-[#00b084]'}`}
              title="Send Message"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" fill="currentColor" stroke="none" />
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
