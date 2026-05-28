import { useState, useEffect } from 'react';
import Sidebar from './components/sidebar/Sidebar';
import ChatWindow from './components/chat/ChatWindow';
import SearchModal from './components/chat/SearchModal';
import { useThemeStore } from './stores/useThemeStore';
import { useAgentBridge } from './stores/useAgentBridge';

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const { theme } = useThemeStore();
  const { connect, status } = useAgentBridge();

  // Connect to the Python backend WebSocket once on app mount.
  // Tauri spawns the Python process at startup; this retries until it's ready.
  useEffect(() => {
    connect();
  }, []);

  // If retries are fully exhausted and status hits 'error', try again every 10s.
  // Calling connect() resets _retries to 0 and starts a fresh retry sequence.
  useEffect(() => {
    if (status !== 'error') return;
    const timer = setTimeout(() => connect(), 10_000);
    return () => clearTimeout(timer);
  }, [status, connect]);

  // Sync theme with document root class list
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'light') {
      root.classList.add('light');
    } else {
      root.classList.remove('light');
    }
  }, [theme]);

  // Global keyboard shortcut for search modal (Ctrl+K or Cmd+K)
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setIsSearchOpen(true);
      }
    };
    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, []);

  return (
    <div className="flex h-screen bg-[var(--bg-sidebar)] text-[var(--text-main)] overflow-hidden select-none font-sans transition-colors duration-150 relative">
      {/* Sidebar - always render to support sliding transitions */}
      <Sidebar 
        isOpen={sidebarOpen} 
        setSidebarOpen={setSidebarOpen} 
        onSearchClick={() => setIsSearchOpen(true)}
      />

      {/* Main Content Area */}
      <div className={`flex-1 flex flex-col min-w-0 bg-[var(--bg-main)] my-2 mr-2 rounded-2xl overflow-hidden transition-all duration-150 ${!sidebarOpen ? 'ml-2' : 'ml-0'}`}>
        {/* Chat Feed & Top Area */}
        <div className="flex-1 overflow-hidden flex flex-col bg-[var(--bg-main)] transition-colors duration-150">
          <ChatWindow sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />
        </div>
      </div>

      {/* Premium Grok-Style Search Modal Overlay */}
      <SearchModal 
        isOpen={isSearchOpen} 
        onClose={() => setIsSearchOpen(false)}
      />
    </div>
  );
}

export default App;