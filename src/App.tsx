import { useEffect, useMemo, useReducer } from 'react'
import { Activity, ChevronDown, CircleHelp, Command, ExternalLink, GitBranch, ShieldCheck, Sparkles } from 'lucide-react'
import { getInitialCase } from './domain/cases'
import type { CaseId } from './domain/types'
import { MockExecutionEventSource } from './engine/MockExecutionEventSource'
import { executionReducer, initialViewState } from './state/executionReducer'
import CaseExplorer from './components/CaseExplorer'
import ExecutionTimeline from './components/ExecutionTimeline'
import ExecutionToolbar from './components/ExecutionToolbar'
import Inspector from './components/Inspector'
import WorkflowCanvas from './components/WorkflowCanvas'
import './index.css'

export default function App() {
  const source = useMemo(() => new MockExecutionEventSource(), [])
  const [state, dispatch] = useReducer(executionReducer, 'CASE-001' as CaseId, initialViewState)
  useEffect(() => source.subscribe((event) => dispatch({ type: 'EVENT', event })), [source])
  const selected = getInitialCase(state.caseId)

  const chooseCase = (caseId: CaseId) => { source.reset(caseId); dispatch({ type: 'CASE', caseId }) }
  const reset = () => { source.reset(state.caseId); dispatch({ type: 'RESET', caseId: state.caseId }) }
  const runCase = () => { dispatch({ type: 'RESET', caseId: state.caseId }); source.startCase(state.caseId) }

  return <div className="app-frame">
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Sparkles size={16} /></div><div><div className="brand-name">order rescue <span>/</span> observatory</div><div className="brand-subtitle">AGENT EXECUTION STUDIO</div></div></div>
      <div className="topbar-center"><span className="project-pill"><GitBranch size={12} /> single stateful workflow <ChevronDown size={12} /></span><span className="top-divider" /><span className="environment-label"><span /> SYNTHETIC ENVIRONMENT</span></div>
      <div className="topbar-right"><span className="build-label"><Activity size={12} /> LOCAL DEMO</span><button className="help-button" aria-label="About this prototype" title="Synthetic developer observability prototype"><CircleHelp size={15} /></button><span className="avatar">OR</span></div>
    </header>
    <ExecutionToolbar state={state} onRun={runCase} onPause={() => { source.pause(); dispatch({ type: 'CONTROL', status: 'PAUSED' }) }} onResume={() => { source.resume(); dispatch({ type: 'CONTROL', status: 'RUNNING' }) }} onStep={() => { source.step(); dispatch({ type: 'CONTROL', status: 'PAUSED' }) }} onReset={reset} onSpeed={(speed) => { source.setSpeed(speed); dispatch({ type: 'SPEED', speed }) }} onAutoFollow={(value) => dispatch({ type: 'AUTO_FOLLOW', value })} />
    <main className="workspace">
      <CaseExplorer selectedCase={state.caseId} state={state} onSelect={chooseCase} />
      <section className="canvas-panel">
        <div className="canvas-heading"><div><span className="eyebrow">EXECUTION GRAPH</span><h1>{state.caseId} <span>·</span> {selected.scenario}</h1></div><div className="canvas-meta"><span><span className="legend-dot running" /> running</span><span><span className="legend-dot completed" /> completed</span><span><span className="legend-dot waiting" /> waiting</span><span><span className="legend-dot blocked" /> blocked</span></div></div>
        <WorkflowCanvas state={state} onSelectNode={(nodeId) => dispatch({ type: 'SELECT_NODE', nodeId })} />
      </section>
      <Inspector state={state} onReply={(reply) => source.submitBuyerReply(reply)} onTimeout={() => source.submitTimeout()} onClearDisruption={() => source.clearDisruption()} />
    </main>
    <ExecutionTimeline state={state} onSelectEvent={(eventId) => dispatch({ type: 'SELECT_EVENT', eventId })} />
    <footer className="app-footer"><span><ShieldCheck size={12} /> Recommendations are simulated and policy constrained</span><span>Order Rescue agent demo <b>·</b> no live logistics integration <ExternalLink size={11} /></span><span className="footer-shortcut"><Command size={11} /> ESC OBSERVATORY</span></footer>
  </div>
}
