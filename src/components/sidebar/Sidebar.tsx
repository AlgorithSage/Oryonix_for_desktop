import { SquarePen, Search, PanelLeftClose, ChevronsUpDown, Trash2 } from 'lucide-react';
import { useChatStore } from '../../stores/useChatStore';

interface SidebarProps {
  isOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  onSearchClick: () => void;
}

export default function Sidebar({ isOpen, setSidebarOpen, onSearchClick }: SidebarProps) {
  const {
    sessions,
    currentSessionId,
    createSession,
    deleteSession,
    selectSession,
  } = useChatStore();

  const filteredSessions = sessions.filter((session) => session.messages.length > 0);

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const isNewChatActive = !currentSession || currentSession.messages.length === 0;

  return (
    <div className={`bg-[var(--bg-sidebar)] flex flex-col h-full shrink-0 select-none border-r border-[var(--border-color)] transition-all duration-300 ease-in-out overflow-hidden
      ${isOpen ? 'w-60 opacity-100 translate-x-0' : 'w-0 opacity-0 -translate-x-8 pointer-events-none border-r-transparent'}`}
    >
      {/* Inner fixed-width container prevents text/layout warping during transition */}
      <div className="w-60 flex flex-col h-full shrink-0">
        {/* Brand Header */}
        <div className="h-14 px-5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex items-center">
              <span className="font-bold text-sm bg-gradient-to-r from-[#F95F1C] to-[#FFC837] bg-clip-text text-transparent tracking-tight font-heading">Oryonix</span>
              <span className="text-[8px] font-mono font-bold border border-[var(--border-color)] text-zinc-500 rounded px-1 py-0.5 ml-1.5 leading-none">
                BETA
              </span>
            </div>
          </div>

          {/* Collapse Sidebar Toggle Icon */}
          <button
            onClick={() => setSidebarOpen(false)}
            className="text-zinc-500 hover:text-[var(--text-main)] transition-colors cursor-pointer p-1 rounded hover:bg-[var(--bg-hover)]"
            title="Collapse Sidebar"
          >
            <PanelLeftClose size={16} />
          </button>
        </div>

        {/* Dynamic Navigation & Session List */}
        <div className="flex-1 px-3 py-4 flex flex-col min-h-0 overflow-hidden">
          {/* Navigation List */}
          <div className="space-y-1 mb-4">
            {/* New Chat Button */}
            <div
              onClick={() => {
                createSession();
              }}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-all border font-sans select-none
                ${isNewChatActive
                  ? 'bg-[var(--bg-hover)] border-[var(--border-color)] text-[var(--text-main)] font-semibold shadow-sm'
                  : 'bg-transparent border-transparent text-zinc-400 hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)]'}`}
            >
              <SquarePen size={15} className={isNewChatActive ? 'text-[#F56C13]' : 'text-zinc-500'} />
              <span className="text-sm font-medium">New Chat</span>
            </div>

            {/* Search Chats Button */}
            <div
              onClick={onSearchClick}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-all border border-transparent text-zinc-400 hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)] font-sans"
            >
              <Search size={15} className="text-zinc-500" />
              <span className="text-sm font-medium">Search Chats</span>
            </div>
          </div>

          {/* Chat Sessions list */}
          <div className="flex-1 overflow-y-auto space-y-1 pr-0.5 custom-scrollbar min-h-0">
            <div className="text-[11px] font-sans tracking-widest text-zinc-500 uppercase px-1 mb-2 font-bold">
              Recent Chats
            </div>
            {filteredSessions.length === 0 ? (
              <div className="text-xs text-zinc-600 px-2 py-3 italic font-sans">
                No conversations yet
              </div>
            ) : (
              filteredSessions.map((session) => {
                const isActive = session.id === currentSessionId;
                return (
                  <div
                    key={session.id}
                    onClick={() => selectSession(session.id)}
                    className={`group relative flex items-center justify-between gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all border font-sans select-none
                      ${isActive
                        ? 'bg-[var(--bg-hover)] border-[var(--border-color)] text-[var(--text-main)] font-medium shadow-sm'
                        : 'bg-transparent border-transparent text-zinc-400 hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)]'}`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <span className="text-sm truncate pr-6">{session.title}</span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteSession(session.id);
                      }}
                      className="absolute right-2 opacity-0 group-hover:opacity-100 p-1 text-zinc-500 hover:text-red-400 transition-all rounded hover:bg-zinc-800/40 cursor-pointer"
                      title="Delete Chat"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Profile Footer */}
        <div className="p-3 bg-transparent flex items-center justify-between cursor-pointer hover:bg-[var(--bg-hover)] transition-colors rounded-lg m-2 border border-transparent hover:border-[var(--border-color)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-xs font-semibold text-white shrink-0">
              U
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-semibold text-[var(--text-main)] truncate">Oryonix</span>
              <span className="text-[11px] text-zinc-500 font-mono -mt-0.5 truncate">Oryonix</span>
            </div>
          </div>
          <ChevronsUpDown size={15} className="text-zinc-500 shrink-0" />
        </div>
      </div>
    </div>
  );
}
