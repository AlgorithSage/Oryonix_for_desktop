import { useState, useEffect } from 'react';
import Sidebar from './components/sidebar/Sidebar';
import ChatWindow from './components/chat/ChatWindow';
import { useThemeStore } from './stores/useThemeStore';

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { theme } = useThemeStore();

  // Sync theme with document root class list
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'light') {
      root.classList.add('light');
    } else {
      root.classList.remove('light');
    }
  }, [theme]);

  return (
    <div className="flex h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-hidden select-none font-sans transition-colors duration-150">
      {/* Sidebar - always render to support sliding transitions */}
      <Sidebar isOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg-main)] transition-colors duration-150">
        {/* Chat Feed & Top Area */}
        <div className="flex-1 overflow-hidden flex flex-col bg-[var(--bg-main)] transition-colors duration-150">
          <ChatWindow sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />
        </div>
      </div>
    </div>
  );
}

export default App;