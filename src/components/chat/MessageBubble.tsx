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
    <div className={`flex items-start gap-4 ${isUser ? 'flex-row-reverse' : 'flex-row'} max-w-4xl mx-auto w-full px-4`}>
      {/* Icon Badge */}
      <div className={`w-7 h-7 rounded border flex items-center justify-center shrink-0 select-none transition-all
        ${isUser 
          ? (isLight ? 'bg-purple-50 border-purple-200 text-purple-600' : 'bg-[#181822] border-[#30303f] text-purple-400')
          : (isLight ? 'bg-zinc-100 border-zinc-200 text-zinc-600' : 'bg-[#0d0d10] border-[#1c1c24] text-zinc-400')}`}>
        {isUser ? <User size={13} /> : <Terminal size={13} />}
      </div>

      {/* Message Box */}
      <div className={`flex-1 min-w-0 p-4 rounded-lg border text-xs leading-relaxed font-sans shadow-sm transition-all
        ${isUser 
          ? (isLight ? 'bg-white border-purple-100 text-zinc-800' : 'bg-[#14141c] border-[#22222f] text-zinc-100')
          : (isLight ? 'bg-white border-zinc-200 text-zinc-800' : 'bg-[#0a0a0d] border-[#141418] text-zinc-200')}`}>
        <div className={`flex items-center justify-between mb-1.5 border-b pb-1 ${isLight ? 'border-zinc-100' : 'border-[#141418]/60'}`}>
          <span className={`font-mono text-[9px] font-bold uppercase tracking-wider ${isLight ? 'text-zinc-400' : 'text-zinc-500'}`}>
            {isUser ? 'User Request' : 'Oryonix Console'}
          </span>
          <span className={`font-mono text-[8px] ${isLight ? 'text-zinc-400' : 'text-zinc-600'}`}>
            {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        </div>
        <p className={`whitespace-pre-wrap font-mono text-[11px] leading-relaxed selection:bg-purple-900/30 selection:text-purple-300 ${isLight ? 'text-zinc-700' : 'text-zinc-200'}`}>
          {message.content}
        </p>
      </div>
    </div>
  );
}
