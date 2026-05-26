import { useState, useEffect, useRef, useMemo } from 'react';
import { Search, X, Maximize2, Minimize2, Trash2 } from 'lucide-react';
import { useChatStore, ChatSession } from '../../stores/useChatStore';
import MessageBubble from './MessageBubble';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function SearchModal({ isOpen, onClose }: SearchModalProps) {
  const { sessions, deleteSession, selectSession } = useChatStore();
  const [query, setQuery] = useState('');
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [showPreviews, setShowPreviews] = useState(true);

  const inputRef = useRef<HTMLInputElement>(null);
  const listContainerRef = useRef<HTMLDivElement>(null);

  // Auto-focus input and reset selection on open
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedSessionId(null);
      const timer = setTimeout(() => inputRef.current?.focus(), 80);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  // Filter sessions that have messages
  const activeSessions = useMemo(() => {
    return sessions.filter((s) => s.messages.length > 0);
  }, [sessions]);

  // Filter sessions matching the query
  const filteredSessions = useMemo(() => {
    return activeSessions.filter((s) =>
      s.title.toLowerCase().includes(query.toLowerCase())
    );
  }, [activeSessions, query]);

  // Group filtered sessions by relative dates
  const groupedSessions = useMemo(() => {
    const groups: { title: string; items: ChatSession[] }[] = [
      { title: 'Today', items: [] },
      { title: 'Yesterday', items: [] },
      { title: 'This Year', items: [] },
      { title: 'Older', items: [] },
    ];

    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
    const startOfYear = new Date(now.getFullYear(), 0, 1).getTime();

    filteredSessions.forEach((s) => {
      const time = s.createdAt;
      if (time >= startOfToday) {
        groups[0].items.push(s);
      } else if (time >= startOfYesterday) {
        groups[1].items.push(s);
      } else if (time >= startOfYear) {
        groups[2].items.push(s);
      } else {
        groups[3].items.push(s);
      }
    });

    return groups.filter((g) => g.items.length > 0);
  }, [filteredSessions]);

  // Create a flat array of grouped items to map keyboard navigation indexes
  const flatGroupedItems = useMemo(() => {
    const items: ChatSession[] = [];
    groupedSessions.forEach((g) => {
      items.push(...g.items);
    });
    return items;
  }, [groupedSessions]);

  // Reset selection to null if the selected session is no longer in the list (e.g. filtered out or deleted)
  useEffect(() => {
    if (selectedSessionId && !flatGroupedItems.some((s) => s.id === selectedSessionId)) {
      setSelectedSessionId(null);
    }
  }, [flatGroupedItems, selectedSessionId]);

  const selectedSession = useMemo(() => {
    return flatGroupedItems.find((s) => s.id === selectedSessionId) || null;
  }, [flatGroupedItems, selectedSessionId]);

  // Format relative timestamps
  const formatTimestamp = (timestamp: number) => {
    const diff = Date.now() - timestamp;
    const hrs = Math.floor(diff / (1000 * 60 * 60));
    if (hrs < 1) return 'Just now';
    if (hrs < 24) return `${hrs} ${hrs === 1 ? 'hour' : 'hours'} ago`;
    
    const days = Math.floor(hrs / 24);
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days} days ago`;

    const date = new Date(timestamp);
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };

  // Keyboard navigation listeners
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Escape -> close
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }

      // Ctrl + P -> toggle preview pane
      if (e.ctrlKey && e.key === 'p') {
        e.preventDefault();
        setShowPreviews((prev) => !prev);
        return;
      }

      // Enter -> Go/Select active session
      if (e.key === 'Enter') {
        e.preventDefault();
        if (selectedSession) {
          selectSession(selectedSession.id);
          onClose();
        }
        return;
      }

      // Arrow navigation
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const currentIdx = flatGroupedItems.findIndex((s) => s.id === selectedSessionId);
        const nextIdx = currentIdx < flatGroupedItems.length - 1 ? currentIdx + 1 : 0;
        if (flatGroupedItems[nextIdx]) {
          setSelectedSessionId(flatGroupedItems[nextIdx].id);
        }
        return;
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        const currentIdx = flatGroupedItems.findIndex((s) => s.id === selectedSessionId);
        const prevIdx = currentIdx > 0 ? currentIdx - 1 : flatGroupedItems.length - 1;
        if (flatGroupedItems[prevIdx]) {
          setSelectedSessionId(flatGroupedItems[prevIdx].id);
        }
        return;
      }

      // Ctrl + D -> Delete selected chat
      if (e.ctrlKey && e.key === 'd') {
        e.preventDefault();
        if (selectedSession) {
          deleteSession(selectedSession.id);
        }
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, flatGroupedItems, selectedSessionId, selectedSession, onClose, selectSession, deleteSession]);

  if (!isOpen) return null;

  // Handle clicking on list item
  const handleItemClick = (sessionId: string) => {
    selectSession(sessionId);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/65 backdrop-blur-xs select-none animate-fade-in font-sans">
      {/* Click outside to close */}
      <div className="absolute inset-0 cursor-default" onClick={onClose} />

      {/* Modal Dialog Container */}
      <div 
        className={`w-full bg-[var(--bg-modal)] border border-[var(--border-modal)] rounded-2xl flex flex-col overflow-hidden shadow-2xl relative animate-fade-in shrink-0 transition-all duration-350 ease-out
          ${showPreviews ? 'max-w-[920px] h-[540px]' : 'max-w-[620px] h-[420px]'}`}
      >
        
        {/* Header Search Box */}
        <div className="h-14 px-6 border-b border-[var(--border-modal)] flex items-center justify-between shrink-0 bg-[var(--bg-modal-header)]">
          <div className="flex-1 flex items-center relative min-w-0">
            <input
              ref={inputRef}
              type="text"
              placeholder="Search..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full bg-transparent text-sm text-[var(--text-modal-title)] placeholder-[var(--text-modal-placeholder)] outline-none pr-10"
              style={{ fontFamily: "'Space Grotesk', sans-serif" }}
            />
            <Search size={16} className="absolute right-4 text-[var(--text-modal-muted)] pointer-events-none" />
          </div>
          <button 
            onClick={onClose}
            className="text-[var(--text-modal-muted)] hover:text-[var(--text-modal-title)] ml-4 p-1 rounded hover:bg-[var(--bg-modal-item-hover)] cursor-pointer transition-colors shrink-0"
            title="Close Search"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content Area */}
        <div 
          onMouseLeave={() => setSelectedSessionId(null)}
          className="flex-1 flex min-h-0 overflow-hidden"
        >
          
          {/* Left Column - Chats List */}
          <div 
            ref={listContainerRef}
            className={`flex flex-col h-full overflow-y-auto py-3.5 pl-4 pr-2 select-none shrink-0 custom-scrollbar transition-all duration-350 ease-out
              ${showPreviews ? 'w-[350px] border-r border-[var(--border-modal)]' : 'w-full border-r-0 border-r-transparent'}`}
          >
            {flatGroupedItems.length === 0 ? (
              <div className="text-xs text-[var(--text-modal-muted)] px-3 py-6 italic text-center font-sans">
                {query ? 'No matching chats found' : 'No recent chats'}
              </div>
            ) : (
              <>
                {groupedSessions.map((group) => (
                  <div key={group.title} className="mb-4">
                    {/* Date group Header */}
                    <div 
                      onMouseEnter={() => setSelectedSessionId(null)}
                      className="text-[9px] font-sans tracking-widest text-[var(--text-modal-muted)] uppercase px-3.5 mb-2 font-bold select-none"
                    >
                      {group.title}
                    </div>

                    {/* Group Items */}
                    <div className="space-y-0.5">
                      {group.items.map((session) => {
                        const isNavigated = session.id === selectedSessionId;
                        return (
                          <div
                            key={session.id}
                            onClick={() => handleItemClick(session.id)}
                            onMouseEnter={(e) => {
                              e.stopPropagation();
                              setSelectedSessionId(session.id);
                            }}
                            className={`group relative flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-lg cursor-pointer transition-all border font-sans select-none
                              ${isNavigated
                                ? 'bg-[var(--bg-modal-item-hover)] border-[var(--border-modal)] text-[var(--text-modal-title)] font-semibold shadow-sm'
                                : 'bg-transparent border-transparent text-[var(--text-modal-muted)] hover:text-[var(--text-modal-title)] hover:bg-[var(--bg-modal-item-hover)]'}`}
                          >
                            <span className="text-xs truncate pr-16">{session.title}</span>
                            <div className="relative flex items-center justify-end min-w-[70px] h-4">
                              <span className="text-[10px] text-[var(--text-modal-placeholder)] font-mono shrink-0 whitespace-nowrap transition-all duration-150 group-hover:opacity-0 group-hover:pointer-events-none">
                                {formatTimestamp(session.createdAt)}
                              </span>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  deleteSession(session.id);
                                }}
                                className="absolute right-0 opacity-0 group-hover:opacity-100 p-1 text-[var(--text-modal-placeholder)] hover:text-red-400 transition-all rounded hover:bg-[var(--bg-modal-item-hover)] cursor-pointer"
                                title="Delete Chat"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
                
                {/* Flex filler to clear selection on hover of empty space below list */}
                <div 
                  className="grow min-h-[30px]" 
                  onMouseEnter={() => setSelectedSessionId(null)} 
                />
              </>
            )}
          </div>

          {/* Right Column - Preview Pane */}
          {showPreviews && (
            <div className="flex-1 bg-[var(--bg-modal-preview)] flex flex-col h-full overflow-hidden select-none">
              {selectedSession ? (
                <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                  {/* Preview Header */}
                  <div className="h-10 px-4 border-b border-[var(--border-modal)]/60 flex items-center bg-[var(--bg-modal-header)] shrink-0">
                    <span className="text-[10px] font-sans text-[var(--text-modal-title)] font-bold truncate max-w-sm">
                      PREVIEWING: {selectedSession.title}
                    </span>
                    <span className="text-[9px] font-mono text-[var(--text-modal-placeholder)] ml-2 font-bold shrink-0">
                      ({selectedSession.messages.length} messages)
                    </span>
                  </div>

                  {/* Messages Feed Preview */}
                  <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar bg-[var(--bg-main)]">
                    {selectedSession.messages.slice(0, 10).map((msg, i) => (
                      <MessageBubble key={i} message={msg} />
                    ))}
                    {selectedSession.messages.length > 10 && (
                      <div className="text-[10px] text-[var(--text-modal-placeholder)] text-center py-1 italic font-sans">
                        Showing first 10 messages of the conversation
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center select-none text-center p-6 gap-2">
                  <p 
                    className="text-sm font-bold text-[var(--text-modal-title)] tracking-wide" 
                    style={{ fontFamily: "'Space Grotesk', sans-serif" }}
                  >
                    Select a conversation to preview
                  </p>
                  <p className="text-xs text-[var(--text-modal-muted)] max-w-xs leading-relaxed font-sans">
                    Use Up/Down arrows to navigate through sessions and instantly inspect their history.
                  </p>
                </div>
              )}
            </div>
          )}

        </div>

        {/* Bottom Shortcuts Bar */}
        <div className="h-10 border-t border-[var(--border-modal)] px-4 flex items-center justify-between bg-[var(--bg-modal-footer)] select-none text-[11px] text-[var(--text-modal-muted)] shrink-0 font-sans">
          <div className="flex items-center gap-3">
            {/* Toggle Preview Expand/Collapse Button */}
            <button
              onClick={() => setShowPreviews((prev) => !prev)}
              className="w-7 h-7 rounded-full bg-[var(--bg-modal)] border border-[var(--border-modal)] flex items-center justify-center text-[var(--text-modal-muted)] hover:text-[var(--text-modal-title)] hover:bg-[var(--bg-modal-item-hover)] cursor-pointer transition-all shadow-sm"
              title={showPreviews ? "Collapse Previews (Ctrl+P)" : "Expand Previews (Ctrl+P)"}
            >
              {showPreviews ? (
                <Minimize2 size={12} className="stroke-[2.5]" />
              ) : (
                <Maximize2 size={12} className="stroke-[2.5]" />
              )}
            </button>
            
            <div className="flex items-center gap-2 bg-[var(--bg-modal)]/60 border border-[var(--border-modal)]/40 rounded-md px-2 py-0.5">
              <span>Show Conversation Previews</span>
              <span className="bg-[var(--bg-modal-item-hover)] text-[var(--text-modal-muted)] px-1 rounded text-[10px] font-mono leading-none py-0.5">Ctrl+P</span>
            </div>
          </div>
          
          <div className="flex items-center gap-5 font-medium">
            <div className="flex items-center gap-2">
              <span>Go</span>
              <span className="bg-[var(--bg-modal-item-hover)] text-[var(--text-modal-muted)] px-1 rounded text-[10px] font-mono leading-none py-0.5">⏎</span>
            </div>
            <div className="flex items-center gap-2">
              <span>Edit</span>
              <span className="bg-[var(--bg-modal-item-hover)] text-[var(--text-modal-muted)] px-1 rounded text-[10px] font-mono leading-none py-0.5">Ctrl+E</span>
            </div>
            <div className="flex items-center gap-2">
              <span>Delete</span>
              <span className="bg-[var(--bg-modal-item-hover)] text-[var(--text-modal-muted)] px-1 rounded text-[10px] font-mono leading-none py-0.5">Ctrl+D</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
