import { Message } from '../../stores/useChatStore';
import { useThemeStore } from '../../stores/useThemeStore';
import { Terminal, User } from 'lucide-react';

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'} w-full`}>
      {/* Icon Badge */}
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 select-none transition-all -mt-0.5
        ${isUser
          ? (isLight ? 'bg-purple-50 text-purple-600' : 'bg-[#27272A] text-purple-400')
          : (isLight ? 'bg-zinc-100 text-zinc-600' : 'bg-[#141414] text-zinc-400')}`}>
        {isUser ? <User size={13} /> : <Terminal size={13} />}
      </div>

      {/* Message Box */}
      <div className={`relative ${isUser ? 'max-w-[80%] w-fit pt-[7px] pb-[9px] px-4 rounded-2xl rounded-tr-none shadow-sm' : 'flex-1 py-1 min-w-0'} font-sans transition-all
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

        <p className={`relative z-10 whitespace-pre-wrap break-words text-[16px] leading-tight selection:bg-purple-900/30 selection:text-purple-300 ${isLight ? 'text-zinc-700' : 'text-zinc-200'}`}>
          {message.content}
        </p>
      </div>
    </div>
  );
}