import { useState, memo } from 'react';
import { useChatStore, Message } from '../../stores/useChatStore';
import { useThemeStore } from '../../stores/useThemeStore';
import { Terminal, User, Copy, Check, Link, ThumbsUp, ThumbsDown, RotateCw, MoreHorizontal, Pencil } from 'lucide-react';

interface MessageBubbleProps {
  message: Message;
  index: number;
}

function MessageBubble({ message, index }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const { theme } = useThemeStore();
  const isLight = theme === 'light';
  const { editMessage } = useChatStore();
  
  const [copied, setCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const adjustHeight = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 72)}px`;
  };

  return (
    <div className={`group flex items-start gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'} w-full`}>
      {/* Icon Badge */}
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 select-none transition-all -mt-0.5
        ${isUser
          ? (isLight ? 'bg-purple-50 text-purple-600' : 'bg-[#27272A] text-purple-400')
          : (isLight ? 'bg-zinc-100 text-zinc-600' : 'bg-[#141414] text-zinc-400')}`}>
        {isUser ? <User size={13} /> : <Terminal size={13} />}
      </div>

      {/* Message Box Container */}
      <div className={`relative ${isUser ? 'max-w-[80%] w-fit flex flex-col items-end' : 'flex-1 py-1 min-w-0'} font-sans transition-all`}>
        {/* Message Content Bubble */}
        <div className={`relative ${isUser ? 'pt-[7px] pb-[9px] px-4 rounded-2xl rounded-tr-none shadow-sm' : ''} transition-all
          ${isUser
            ? (isLight ? 'bg-purple-100 text-zinc-800' : 'bg-[#27272A] text-zinc-100')
            : 'bg-transparent text-zinc-200 border-none shadow-none'}`}>

          {/* WhatsApp-style Tail */}
          {isUser && (
            <svg
              className="absolute -right-[8px] top-0 w-[8px] h-[8px] overflow-visible"
              viewBox="0 0 8 8"
            >
              <path
                d="M0 0 H8 L0 8 Z"
                fill={isLight ? '#ede9fe' : '#27272A'}
              />
            </svg>
          )}

          {isEditing ? (
            <div className="flex flex-col w-[280px] xs:w-[350px] sm:w-[450px] md:w-[550px] lg:w-[620px] max-w-full relative z-10">
              <textarea
                value={editContent}
                onChange={(e) => {
                  setEditContent(e.target.value);
                  adjustHeight(e.target);
                }}
                className={`w-full bg-transparent text-[16px] leading-tight outline-none resize-none border-none py-1 relative z-10 selection:bg-purple-900/30 selection:text-purple-300 font-sans overflow-y-auto max-h-[72px] h-auto min-h-[24px] custom-scrollbar ${isLight ? 'text-zinc-800' : 'text-zinc-100'}`}
                ref={(el) => {
                  if (el) {
                    el.focus();
                    el.selectionStart = el.value.length;
                    el.selectionEnd = el.value.length;
                    adjustHeight(el);
                  }
                }}
              />
              <div className="flex items-center justify-end gap-1.5 mt-2.5 select-none relative z-10">
                <button
                  onClick={() => {
                    setIsEditing(false);
                    setEditContent(message.content);
                  }}
                  className={`px-2.5 py-1 text-[11.5px] transition-all cursor-pointer font-sans font-semibold border-none bg-transparent outline-none
                    ${isLight 
                      ? 'text-zinc-500 hover:text-[var(--text-action-hover)]' 
                      : 'text-zinc-400 hover:text-[var(--text-action-hover)]'}`}
                >
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    if (editContent.trim() && editContent !== message.content) {
                      setIsEditing(false);
                      await editMessage(index, editContent);
                    } else {
                      setIsEditing(false);
                    }
                  }}
                  className="px-3 py-1 text-[11.5px] rounded-full bg-purple-600 hover:bg-purple-700 text-white font-semibold shadow-sm transition-all cursor-pointer font-sans"
                >
                  Save & Submit
                </button>
              </div>
            </div>
          ) : (
            <p className={`relative z-10 whitespace-pre-wrap break-words text-[16px] leading-tight selection:bg-purple-900/30 selection:text-purple-300 ${isLight ? 'text-zinc-700' : 'text-zinc-200'}`}>
              {message.content}
            </p>
          )}
        </div>

        {/* AI Action Bar */}
        {!isUser && (
          <div className="flex items-center gap-1 mt-2 -ml-1.5 text-zinc-400 dark:text-zinc-500 opacity-0 group-hover:opacity-100 transition-opacity duration-150 select-none">
            {/* Copy Button */}
            <button
              onClick={handleCopy}
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="Copy response"
            >
              {copied ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
            </button>

            {/* Link Button */}
            <button
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="Copy link"
            >
              <Link size={13} />
            </button>

            {/* Like Button */}
            <button
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="Good response"
            >
              <ThumbsUp size={13} />
            </button>

            {/* Dislike Button */}
            <button
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="Bad response"
            >
              <ThumbsDown size={13} />
            </button>

            {/* Regenerate Button */}
            <button
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="Regenerate response"
            >
              <RotateCw size={13} />
            </button>

            {/* More Button */}
            <button
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="More"
            >
              <MoreHorizontal size={13} />
            </button>
          </div>
        )}

        {/* User Action Bar */}
        {isUser && !isEditing && (
          <div className="flex items-center gap-1 mt-1.5 mr-1 text-zinc-400 dark:text-zinc-500 opacity-0 group-hover:opacity-100 transition-opacity duration-150 select-none">
            {/* Edit Button */}
            <button
              onClick={() => setIsEditing(true)}
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="Edit"
            >
              <Pencil size={13} />
            </button>

            {/* Copy Button */}
            <button
              onClick={handleCopy}
              className="p-1.5 rounded-full hover:bg-[var(--bg-hover)] hover:text-[var(--text-action-hover)] transition-all cursor-pointer flex items-center justify-center"
              title="Copy"
            >
              {copied ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(MessageBubble);