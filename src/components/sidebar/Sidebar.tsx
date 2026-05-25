import { SquarePen, Search, PanelLeftClose, ChevronsUpDown } from 'lucide-react';

interface SidebarProps {
  isOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

export default function Sidebar({ isOpen, setSidebarOpen }: SidebarProps) {
  return (
    <div className={`bg-[var(--bg-sidebar)] flex flex-col h-full shrink-0 select-none border-r border-[var(--border-color)] transition-all duration-300 ease-in-out overflow-hidden
      ${isOpen ? 'w-60 opacity-100 translate-x-0' : 'w-0 opacity-0 -translate-x-8 pointer-events-none border-r-transparent'}`}
    >
      {/* Inner fixed-width container prevents text/layout warping during transition */}
      <div className="w-60 flex flex-col h-full shrink-0">
        {/* Brand Header */}
        <div className="h-14 px-5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            {/* Circular Green Brand Icon */}
            <div className="w-6 h-6 rounded-full bg-[#00c896] flex items-center justify-center shadow-md">
              <span className="text-black font-extrabold text-[10px]">o</span>
            </div>
            <div className="flex items-center">
              <span className="font-bold text-sm text-[var(--text-main)] tracking-tight font-heading">oryonix</span>
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

        {/* Navigation List */}
        <div className="flex-1 px-3 py-4 space-y-6 overflow-y-auto">
          <div className="space-y-1">
            <SidebarItem icon={SquarePen} label="New Chat" active />
            <SidebarItem icon={Search} label="Search" />
          </div>
        </div>

        {/* Profile Footer */}
        <div className="p-3 bg-transparent flex items-center justify-between cursor-pointer hover:bg-[var(--bg-hover)] transition-colors rounded-lg m-2 border border-transparent hover:border-[var(--border-color)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-xs font-semibold text-white shrink-0">
              U
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-semibold text-[var(--text-main)] truncate">Oryonix</span>
              <span className="text-[9px] text-zinc-500 font-mono -mt-0.5 truncate">Oryonix</span>
            </div>
          </div>
          <ChevronsUpDown size={14} className="text-zinc-500 shrink-0" />
        </div>
      </div>
    </div>
  );
}

function SidebarItem({ icon: Icon, label, active = false }: { 
  icon: any; 
  label: string; 
  active?: boolean;
}) {
  return (
    <div className={`flex items-center gap-2.5 px-3 py-2 rounded-md cursor-pointer transition-all
      ${active 
        ? 'bg-[var(--bg-hover)] text-[var(--text-main)] font-semibold border border-[var(--border-color)]' 
        : 'bg-transparent text-zinc-500 hover:text-[var(--text-main)] hover:bg-[var(--bg-hover)]'}`}>
      <Icon size={15} className={active ? "text-[var(--text-main)]" : "text-zinc-500"} />
      <span className="text-xs font-medium">{label}</span>
    </div>
  );
}
