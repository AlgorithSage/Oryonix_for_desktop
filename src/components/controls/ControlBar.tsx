import { useState, useEffect } from 'react';
import { Square, Pause, Cpu, HardDrive } from 'lucide-react';
import { useChatStore } from '../../stores/useChatStore';

export default function ControlBar() {
  const { isThinking } = useChatStore();
  const [autonomous, setAutonomous] = useState(true);
  const [cpu, setCpu] = useState(2.4);
  const [ram, setRam] = useState(132);

  // Simulate live hardware metrics
  useEffect(() => {
    const interval = setInterval(() => {
      setCpu(parseFloat((Math.random() * 3 + (isThinking ? 12.1 : 1.5)).toFixed(1)));
      setRam(Math.floor(130 + Math.random() * 8 + (isThinking ? 25 : 0)));
    }, 2000);
    return () => clearInterval(interval);
  }, [isThinking]);

  return (
    <div className="h-12 border-t border-[var(--border-color)] bg-[var(--bg-control)] px-6 flex items-center justify-between select-none shrink-0 font-mono text-[10px] transition-colors duration-150">
      {/* Left: Hardware Metrics */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-zinc-500">
          <Cpu size={12} className="text-zinc-500" />
          <span>CPU</span>
          <span className="text-[var(--text-main)] font-semibold w-8 text-right bg-[var(--bg-hover)] px-1 py-0.5 rounded border border-[var(--border-color)]">{cpu}%</span>
        </div>
        <div className="flex items-center gap-1.5 text-zinc-500">
          <HardDrive size={12} className="text-zinc-500" />
          <span>RAM</span>
          <span className="text-[var(--text-main)] font-semibold w-12 text-right bg-[var(--bg-hover)] px-1 py-0.5 rounded border border-[var(--border-color)]">{ram} MB</span>
        </div>
      </div>

      {/* Center: System Status */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">MODE:</span>
          <button 
            onClick={() => setAutonomous(!autonomous)}
            className={`px-2 py-0.5 rounded border transition-all cursor-pointer font-bold uppercase text-[9px]
              ${autonomous 
                ? 'bg-purple-950/20 border-purple-800 text-purple-300' 
                : 'bg-[var(--bg-hover)] border-[var(--border-color)] text-[var(--text-muted)]'}`}
          >
            {autonomous ? 'Autonomous' : 'Semi-Auto'}
          </button>
        </div>
        <div className="h-3 w-px bg-[var(--border-color)]"></div>
        <div className="flex items-center gap-1.5">
          <span className="text-zinc-500 font-mono">STATUS:</span>
          <span className={`font-bold uppercase text-[9px] flex items-center gap-1
            ${isThinking ? 'text-amber-500' : 'text-emerald-500'}`}>
            <span className={`w-1 h-1 rounded-full ${isThinking ? 'bg-amber-500 animate-ping' : 'bg-emerald-500 animate-pulse'}`}></span>
            {isThinking ? 'Executing Plan' : 'System Idle'}
          </span>
        </div>
      </div>

      {/* Right: Operational Controls */}
      <div className="flex items-center gap-2">
        <button 
          className="px-2.5 py-1 rounded bg-[var(--bg-hover)] border border-[var(--border-color)] hover:border-zinc-500 text-[var(--text-main)] transition-all cursor-pointer flex items-center gap-1.5"
          title="Pause Execution"
        >
          <Pause size={10} />
          <span>Pause</span>
        </button>

        <button 
          className="px-2.5 py-1 rounded bg-transparent border border-red-900/60 text-red-400 hover:bg-red-950/40 hover:border-red-800 transition-all cursor-pointer flex items-center gap-1.5"
          title="Force Kill Operations"
        >
          <Square size={9} fill="currentColor" className="opacity-90" />
          <span>Kill</span>
        </button>
      </div>
    </div>
  );
}
