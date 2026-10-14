import { Pause, Play, RotateCcw, SkipForward, Zap } from 'lucide-react'
import type { ExecutionViewState, Speed } from '../domain/types'

interface Props { state: ExecutionViewState; onRun: () => void; onPause: () => void; onResume: () => void; onStep: () => void; onReset: () => void; onSpeed: (speed: Speed) => void; onAutoFollow: (value: boolean) => void }
export default function ExecutionToolbar({ state, onRun, onPause, onResume, onStep, onReset, onSpeed, onAutoFollow }: Props) {
  const active = state.status === 'RUNNING'
  return <div className="execution-toolbar">
    <div className="toolbar-left"><span className="toolbar-label">EXECUTION</span><span className={`run-state state-${state.status.toLowerCase()}`}><i />{state.status.replaceAll('_', ' ')}</span></div>
    <div className="toolbar-actions">
      <button className="button-primary" onClick={onRun} disabled={active}><Play size={13} fill="currentColor" /> Run case</button>
      <button className="icon-button" title="Pause" onClick={onPause} disabled={!active}><Pause size={14} /></button>
      <button className="icon-button" title="Resume" onClick={onResume} disabled={active || state.status === 'IDLE' || state.status === 'COMPLETED'}><Play size={14} /></button>
      <button className="icon-button" title="Step forward" onClick={onStep} disabled={state.status === 'IDLE' || state.status === 'COMPLETED'}><SkipForward size={14} /></button>
      <span className="toolbar-divider" />
      <button className="icon-button" title="Reset execution" onClick={onReset}><RotateCcw size={14} /></button>
      <span className="toolbar-divider" />
      <span className="speed-label"><Zap size={12} /> SPEED</span>
      <select value={state.speed} onChange={(e) => onSpeed(e.target.value as Speed)} aria-label="Execution speed"><option>0.5x</option><option>1x</option><option>2x</option><option>Instant</option></select>
    </div>
    <label className="follow-toggle"><input type="checkbox" checked={state.autoFollow} onChange={(e) => onAutoFollow(e.target.checked)} /><span className="toggle-track" /><span>Follow events</span></label>
  </div>
}
