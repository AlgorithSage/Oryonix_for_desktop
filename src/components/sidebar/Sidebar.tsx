import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { SquarePen, Search, PanelLeftClose, Trash2, Pin, PinOff, Pencil, X, Check, Settings, Blocks, Clock, HelpCircle, Compass, LogOut, ChevronRight, ChevronDown } from 'lucide-react';
import { useChatStore, ChatSession } from '../../stores/useChatStore';

interface SidebarProps {
  isOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  onSearchClick: () => void;
}

interface SidebarChatItemProps {
  session: ChatSession;
  currentSessionId: string | null;
  selectSession: (id: string) => void;
  deleteSession: (id: string) => void;
  togglePinSession: (id: string) => void;
  renameSession: (id: string, title: string) => void;
  formatTimestamp?: (timestamp: number) => string;
  showTimestamp?: boolean;
}

const SidebarChatItem = memo(function SidebarChatItem({
  session,
  currentSessionId,
  selectSession,
  deleteSession,
  togglePinSession,
  renameSession,
  formatTimestamp,
  showTimestamp = false,
}: SidebarChatItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(session.title);
  const inputRef = useRef<HTMLInputElement>(null);

  const isActive = session.id === currentSessionId;

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      const len = inputRef.current.value.length;
      inputRef.current.setSelectionRange(len, len);
    }
  }, [isEditing]);

  const handleSave = () => {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== session.title) {
      renameSession(session.id, trimmed);
    }
    setIsEditing(false);
  };

  const handleCancel = () => {
    setEditTitle(session.title);
    setIsEditing(false);
  };

  return (
    <div
      onClick={() => {
        if (!isEditing) {
          selectSession(session.id);
        }
      }}
      className={`group relative flex items-center justify-between gap-3 px-3 py-1.5 rounded-xl cursor-pointer transition-colors duration-150 ease-out border font-sans select-none
        ${isActive
          ? 'bg-[var(--bg-hover)] border-[var(--border-color)] text-[var(--text-main)] font-medium shadow-sm'
          : 'bg-transparent border-transparent text-[var(--text-sidebar-item)] hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)]'}`}
    >
      {isEditing ? (
        <div
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-2 w-full pr-1"
        >
          <input
            ref={inputRef}
            type="text"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={handleSave}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave();
              if (e.key === 'Escape') handleCancel();
            }}
            className="text-[13px] bg-transparent text-[var(--text-main)] outline-none w-full font-normal"
          />

          <div className="flex items-center gap-2 shrink-0 -mr-1.5">
            {/* Cancel Button */}
            <button
              onMouseDown={(e) => {
                e.preventDefault();
                handleCancel();
              }}
              className="p-0.5 text-[var(--text-sidebar-muted)] hover:text-[var(--text-action-hover)] cursor-pointer transition-colors duration-150"
              title="Cancel"
            >
              <X size={14} />
            </button>

            {/* Confirm Button */}
            <button
              onMouseDown={(e) => {
                e.preventDefault();
                handleSave();
              }}
              className="p-0.5 text-[var(--text-sidebar-muted)] hover:text-[var(--text-action-hover)] cursor-pointer transition-colors duration-150"
              title="Save"
            >
              <Check size={14} />
            </button>
          </div>
        </div>
      ) : (
        <>
          <span className="text-[13px] truncate flex-1 pr-1 transition-all duration-150">
            {session.title}
          </span>
          <div className="relative flex items-center justify-end h-4 shrink-0 transition-all duration-150 w-[52px] min-w-[52px]">
            {/* Show timestamp only when requested AND not hovered */}
            {showTimestamp && formatTimestamp && (
              <span className="text-[10px] text-[var(--text-sidebar-muted)] font-mono shrink-0 whitespace-nowrap transition-all duration-150 group-hover:opacity-0 group-hover:pointer-events-none">
                {formatTimestamp(session.createdAt)}
              </span>
            )}

            {/* Hover Actions */}
            <div className="absolute right-0 opacity-0 group-hover:opacity-100 flex items-center gap-1.5 transition-all duration-150 ease-out bg-transparent">
              {/* Pin Action */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  togglePinSession(session.id);
                }}
                className={`p-0.5 cursor-pointer transition-colors duration-150
                  ${session.pinned ? 'text-[#F56C13] hover:text-[#e05e0d]' : 'text-[var(--text-sidebar-muted)] hover:text-[var(--text-action-hover)]'}`}
                title={session.pinned ? "Unpin Chat" : "Pin Chat"}
              >
                {session.pinned ? (
                  <PinOff size={13} />
                ) : (
                  <Pin size={13} className={session.pinned ? 'fill-[#F56C13]' : ''} />
                )}
              </button>

              {/* Rename Action */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setEditTitle(session.title);
                  setIsEditing(true);
                }}
                className="p-0.5 text-[var(--text-sidebar-muted)] hover:text-[var(--text-action-hover)] cursor-pointer transition-colors duration-150"
                title="Rename Chat"
              >
                <Pencil size={13} />
              </button>

              {/* Delete Action */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteSession(session.id);
                }}
                className="p-0.5 text-[var(--text-sidebar-muted)] hover:text-red-500 cursor-pointer transition-colors duration-150"
                title="Delete Chat"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
});

export default function Sidebar({ isOpen, setSidebarOpen, onSearchClick }: SidebarProps) {
  const {
    sessions,
    currentSessionId,
    createSession,
    deleteSession,
    selectSession,
    togglePinSession,
    renameSession,
  } = useChatStore();

  const [isExpanded, setIsExpanded] = useState(() => {
    const saved = localStorage.getItem('oryonix_recent_chats_expanded');
    return saved !== null ? saved === 'true' : true;
  });

  const toggleExpand = () => {
    setIsExpanded((prev) => {
      const next = !prev;
      localStorage.setItem('oryonix_recent_chats_expanded', String(next));
      return next;
    });
  };

  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const profileButtonRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        profileMenuRef.current &&
        !profileMenuRef.current.contains(event.target as Node) &&
        profileButtonRef.current &&
        !profileButtonRef.current.contains(event.target as Node)
      ) {
        setIsProfileMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Filter out empty chats (sessions with at least 1 message are active)
  const filteredSessions = useMemo(() => {
    return sessions.filter((session) => session.messages.length > 0);
  }, [sessions]);

  // Separate pinned chats
  const pinnedSessions = useMemo(() => {
    return filteredSessions.filter((s) => s.pinned);
  }, [filteredSessions]);

  // Separate unpinned chats for recent list
  const unpinnedSessions = useMemo(() => {
    return filteredSessions.filter((s) => !s.pinned);
  }, [filteredSessions]);

  // Limit displayed chats in sidebar to a premium threshold (e.g. 15 chats max)
  const MAX_DISPLAY_CHATS = 15;
  const displayedSessions = useMemo(() => {
    return unpinnedSessions.slice(0, MAX_DISPLAY_CHATS);
  }, [unpinnedSessions]);

  const hasMoreSessions = unpinnedSessions.length > MAX_DISPLAY_CHATS;

  // Group displayed sessions dynamically by relative dates (Grok style!)
  const groupedRecentChats = useMemo(() => {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
    const sevenDaysAgo = startOfToday - 6 * 24 * 60 * 60 * 1000;

    const groups: { [key: string]: ChatSession[] } = {};
    const groupOrder: string[] = [];

    displayedSessions.forEach((session) => {
      const time = session.createdAt;
      let groupName = '';

      if (time >= startOfToday) {
        groupName = 'Today';
      } else if (time >= startOfYesterday) {
        groupName = 'Yesterday';
      } else if (time >= sevenDaysAgo) {
        groupName = 'Previous 7 Days';
      } else {
        // Group by Month Year (e.g., "May 2026")
        const date = new Date(time);
        const month = date.toLocaleString('default', { month: 'long' });
        const year = date.getFullYear();
        groupName = `${month} ${year}`;
      }

      if (!groups[groupName]) {
        groups[groupName] = [];
        groupOrder.push(groupName);
      }
      groups[groupName].push(session);
    });

    return groupOrder.map((name) => ({
      title: name,
      items: groups[name],
    }));
  }, [displayedSessions]);

  // Format relative sidebar timestamps
  const formatSidebarTimestamp = (timestamp: number) => {
    const diff = Date.now() - timestamp;
    const mins = Math.floor(diff / (1000 * 60));
    if (mins < 1) return '1m ago';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;

    const days = Math.floor(hrs / 24);
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days}d ago`;

    const date = new Date(timestamp);
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };

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
            <span className="font-bold text-[22px] bg-gradient-to-r from-[#F95F1C] to-[#FFC837] bg-clip-text text-transparent tracking-tight font-heading">
              Oryonix
            </span>
          </div>

          {/* Collapse Sidebar Toggle Icon */}
          <button
            onClick={() => setSidebarOpen(false)}
            className="text-zinc-500 hover:text-[var(--text-main)] transition-colors cursor-pointer p-1.5 rounded hover:bg-[var(--bg-hover)]"
            title="Collapse Sidebar"
          >
            <PanelLeftClose size={16} />
          </button>
        </div>

        {/* Dynamic Navigation & Session List */}
        <div className="flex-1 px-3 py-4 flex flex-col min-h-0 overflow-hidden">
          {/* Navigation List */}
          <div className="space-y-1 mb-6 shrink-0">
            {/* New Chat Button */}
            <div
              onClick={() => {
                createSession();
              }}
              className={`flex items-center gap-3 px-3 py-1.5 rounded-xl cursor-pointer transition-all border font-sans select-none
                ${isNewChatActive
                  ? 'bg-[var(--bg-hover)] border-[var(--border-color)] text-[var(--text-main)] font-semibold shadow-sm'
                  : 'bg-transparent border-transparent text-[var(--text-sidebar-item)] hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)]'}`}
            >
              <SquarePen size={18} className={isNewChatActive ? 'text-[#F56C13]' : 'text-[var(--text-sidebar-item)]'} />
              <span className="text-sm font-medium">New Chat</span>
            </div>

            {/* Search Chats Button */}
            <div
              onClick={onSearchClick}
              className="flex items-center gap-3 px-3 py-1.5 rounded-xl cursor-pointer transition-all border border-transparent text-[var(--text-sidebar-item)] hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)] font-sans"
            >
              <Search size={18} className="text-[var(--text-sidebar-item)]" />
              <span className="text-sm font-medium">Search Chats</span>
            </div>
          </div>

          {/* Chat Sessions list */}
          <div className="flex-1 overflow-y-auto pr-1 custom-scrollbar min-h-0 relative flex flex-col space-y-1">
            {filteredSessions.length === 0 ? (
              <div className="text-xs text-zinc-600 px-3 py-3 italic font-sans">
                No conversations yet
              </div>
            ) : (
              <>
                {/* Recent Chats Header - Collapsible */}
                <div 
                  onClick={toggleExpand}
                  className="flex items-center justify-between text-[11px] font-sans tracking-wider text-[var(--text-sidebar-header)] font-semibold px-4 mb-2 cursor-pointer hover:text-[var(--text-main)] select-none group/header transition-colors"
                >
                  <span>RECENTS</span>
                  <ChevronDown 
                    size={12} 
                    className={`text-[var(--text-sidebar-muted)] group-hover/header:text-[var(--text-main)] transition-transform duration-200 ${
                      isExpanded ? '' : '-rotate-90'
                    }`} 
                  />
                </div>

                {/* Collapsible Content */}
                {isExpanded && (
                  <div className="space-y-4 pt-1 flex flex-col">
                    {/* 1. Pinned Chats Section */}
                    {pinnedSessions.length > 0 && (
                      <div className="relative space-y-1 mb-2 shrink-0">
                        {/* Sticky Pinned Header */}
                        <div className="sticky top-0 z-10 bg-[var(--bg-sidebar)] flex items-center gap-1.5 py-1.5 select-none pr-2.5">
                          <span className="text-[9px] font-sans tracking-widest text-[#F56C13] uppercase font-bold pl-3.5 shrink-0 flex items-center gap-1">
                            <Pin size={10} className="fill-[#F56C13]" /> Pinned
                          </span>
                          <div className="h-[1px] flex-1 bg-[var(--timeline-divider)] mr-1.5 opacity-40" />
                        </div>

                        {/* Pinned Items list */}
                        <div className="space-y-0.5 pr-3">
                          {pinnedSessions.map((session) => (
                            <SidebarChatItem
                              key={session.id}
                              session={session}
                              currentSessionId={currentSessionId}
                              selectSession={selectSession}
                              deleteSession={deleteSession}
                              togglePinSession={togglePinSession}
                              renameSession={renameSession}
                            />
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 2. Date Groups */}
                    {groupedRecentChats.map((group) => (
                      <div key={group.title} className="relative space-y-1">
                        {/* Sticky Date group Header */}
                        <div className="sticky top-0 z-10 bg-[var(--bg-sidebar)] flex items-center gap-2.5 py-1.5 select-none pr-2.5">
                          <span className="text-[9px] font-sans tracking-widest text-[var(--text-sidebar-header)] uppercase font-bold pl-3.5 shrink-0">
                            {group.title}
                          </span>
                          <div className="h-[1px] flex-1 bg-[var(--timeline-divider)] mr-1.5" />
                        </div>

                        {/* Group Items */}
                        <div className="space-y-0.5 pr-3">
                          {group.items.map((session) => (
                            <SidebarChatItem
                              key={session.id}
                              session={session}
                              currentSessionId={currentSessionId}
                              selectSession={selectSession}
                              deleteSession={deleteSession}
                              togglePinSession={togglePinSession}
                              renameSession={renameSession}
                              formatTimestamp={formatSidebarTimestamp}
                              showTimestamp={group.title === 'Today'}
                            />
                          ))}
                        </div>
                      </div>
                    ))}

                    {/* See All Button */}
                    {hasMoreSessions && (
                      <div className="pt-2 px-1 pr-3">
                        <button
                          onClick={onSearchClick}
                          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-full border border-[var(--border-color)] hover:border-zinc-700 bg-transparent text-xs font-semibold text-zinc-400 hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)] transition-all duration-150 cursor-pointer select-none font-sans"
                        >
                          See All Chats
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Profile Footer Wrapper with Popup Menu */}
        <div className="relative mx-2 mb-2 shrink-0">
          {/* Popup Dropdown Menu */}
          {isProfileMenuOpen && (
            <div
              ref={profileMenuRef}
              className="absolute bottom-[55px] left-0 right-0 z-50 bg-[var(--bg-popover)] border border-[var(--border-popover)] rounded-2xl shadow-2xl p-1.5 flex flex-col gap-0.5 animate-modal-in font-sans"
            >
              {/* Settings */}
              <button
                onClick={() => setIsProfileMenuOpen(false)}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 text-[13px] text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] hover:bg-[var(--bg-popover-item-hover)] rounded-xl cursor-pointer transition-all duration-150 font-medium"
              >
                <Settings size={15} className="text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] shrink-0 transition-colors duration-150" />
                <span className="flex-grow text-left">Settings</span>
              </button>

              {/* Connectors */}
              <button
                onClick={() => setIsProfileMenuOpen(false)}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 text-[13px] text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] hover:bg-[var(--bg-popover-item-hover)] rounded-xl cursor-pointer transition-all duration-150 font-medium"
              >
                <Blocks size={15} className="text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] shrink-0 transition-colors duration-150" />
                <span className="flex-grow text-left">Connectors</span>
              </button>

              {/* Tasks */}
              <button
                onClick={() => setIsProfileMenuOpen(false)}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 text-[13px] text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] hover:bg-[var(--bg-popover-item-hover)] rounded-xl cursor-pointer transition-all duration-150 font-medium"
              >
                <Clock size={15} className="text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] shrink-0 transition-colors duration-150" />
                <span className="flex-grow text-left">Tasks</span>
              </button>

              {/* Help */}
              <button
                onClick={() => setIsProfileMenuOpen(false)}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 text-[13px] text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] hover:bg-[var(--bg-popover-item-hover)] rounded-xl cursor-pointer transition-all duration-150 font-medium"
              >
                <HelpCircle size={15} className="text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] shrink-0 transition-colors duration-150" />
                <span className="flex-grow text-left">Help</span>
                <ChevronRight size={13} className="text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] shrink-0 transition-colors duration-150" />
              </button>

              {/* Upgrade Plan */}
              <button
                onClick={() => setIsProfileMenuOpen(false)}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 text-[13px] text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] hover:bg-[var(--bg-popover-item-hover)] rounded-xl cursor-pointer transition-all duration-150 font-medium"
              >
                <Compass size={15} className="text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] shrink-0 transition-colors duration-150" />
                <span className="flex-grow text-left">Upgrade plan</span>
              </button>

              {/* Sign Out */}
              <button
                onClick={() => setIsProfileMenuOpen(false)}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 text-[13px] text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] hover:bg-[var(--bg-popover-item-hover)] rounded-xl cursor-pointer transition-all duration-150 font-medium"
              >
                <LogOut size={15} className="text-[var(--text-popover-item)] hover:text-[var(--text-popover-item-hover)] shrink-0 transition-colors duration-150" />
                <span className="flex-grow text-left">Sign Out</span>
              </button>
            </div>
          )}

        </div>

        {/* Profile Footer */}
        <div className="p-3 bg-transparent flex items-center justify-between m-2 border border-transparent rounded-xl transition-all">
          <div className="flex items-center gap-3 min-w-0">
            {/* Glossy gradient avatar */}
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-[#E0245E] to-[#F56C13] flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm">
              S
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-semibold text-[var(--text-main)] truncate leading-none">Subhankar Patra</span>
              <span className="text-[10px] text-zinc-500 font-medium tracking-wide mt-1 leading-none">Pro</span>
            </div>
          </div>
          <button 
            onClick={() => setIsProfileMenuOpen(!isProfileMenuOpen)}
            className="text-zinc-500 hover:text-[var(--text-main)] transition-colors p-1.5 rounded-full hover:bg-zinc-800/10 dark:hover:bg-zinc-100/10 cursor-pointer" 
            title="Settings"
          >
            <Settings size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
