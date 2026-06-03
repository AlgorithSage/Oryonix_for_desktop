import { useState, useEffect } from 'react';
import { Square, Pause, Play, Cpu, HardDrive } from 'lucide-react';
import { useChatStore } from '../../stores/useChatStore';
import { useAgentBridge } from '../../stores/useAgentBridge';

export default function ControlBar() {
  const { isThinking } = useChatStore();
  const { isPaused, sendPauseTask, sendResumeTask, sendKillTask } = useAgentBridge();
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
            {isThinking ? (isPaused ? 'Execution Paused' : 'Executing Plan') : 'System Idle'}
          </span>
        </div>
      </div>

      {/* Right: Operational Controls */}
      <div className="flex items-center gap-2">
        {isThinking && (
          <button 
            onClick={isPaused ? sendResumeTask : sendPauseTask}
            className={`px-2.5 py-1 rounded border transition-all cursor-pointer flex items-center gap-1.5 
              ${isPaused 
                ? 'bg-purple-950/30 border-purple-700 text-purple-300 hover:bg-purple-900/40' 
                : 'bg-[var(--bg-hover)] border-[var(--border-color)] hover:border-zinc-500 text-[var(--text-main)]'
              }`}
            title={isPaused ? "Resume Execution" : "Pause Execution"}
          >
            {isPaused ? <Play size={10} fill="currentColor" /> : <Pause size={10} />}
            <span>{isPaused ? 'Resume' : 'Pause'}</span>
          </button>
        )}

        <button 
          onClick={sendKillTask}
          disabled={!isThinking}
          className={`px-2.5 py-1 rounded transition-all flex items-center gap-1.5
            ${isThinking 
              ? 'bg-transparent border border-red-900/60 text-red-400 hover:bg-red-950/40 hover:border-red-800 cursor-pointer' 
              : 'bg-transparent border border-[var(--border-color)] text-zinc-600 cursor-not-allowed opacity-50'
            }`}
          title="Force Kill Operations"
        >
          <Square size={9} fill={isThinking ? "currentColor" : "none"} className="opacity-95" />
          <span>Kill</span>
        </button>
      </div>
    </div>
  );
}
