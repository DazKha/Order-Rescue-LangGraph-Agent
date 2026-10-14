import { useEffect, useRef } from 'react'
import { AlertTriangle, Check, Circle, Clock3, ShieldCheck, Sparkles } from 'lucide-react'
import type { ExecutionEvent, ExecutionViewState } from '../domain/types'

interface Props { state: ExecutionViewState; onSelectEvent: (eventId: string) => void }
const time = (index: number) => `[${String(Math.floor(index / 60)).padStart(2, '0')}:${String(index % 60).padStart(2, '0')}]`
function iconFor(event: ExecutionEvent) {
  if (event.category === 'POLICY') return <ShieldCheck size={12} />
  if (event.category === 'RESULT') return <Sparkles size={12} />
  if (event.status === 'ESCALATED' || event.status === 'BLOCKED') return <AlertTriangle size={12} />
  if (event.eventType === 'NODE_COMPLETED') return <Check size={12} />
  return <Circle size={9} />
}
function titleFor(event: ExecutionEvent) {
  const name = event.nodeId.replaceAll('_', ' ')
  if (event.output && typeof event.output === 'object' && 'recommendation' in event.output) return `Recommendation · ${String((event.output as { recommendation: unknown }).recommendation).replaceAll('_', ' ')}`
  if (event.eventType === 'BUYER_REPLY') return 'BUYER_REPLY received'
  if (event.eventType === 'TIMEOUT') return 'Simulated buyer timeout'
  if (event.eventType === 'POLICY_RULE_EVALUATED') return event.content ?? 'Policy rule evaluated'
  if (event.eventType === 'POLICY_DECISION') return `Policy decision · ${event.policy?.decision ?? ''}`
  if (event.category && event.content) return event.content
  if (event.eventType === 'NODE_COMPLETED') return `${name} completed${event.summary ? ` · ${event.summary}` : ''}`
  if (event.eventType === 'NODE_STARTED') return `${name} started`
  return event.content ?? event.summary ?? event.eventType.replaceAll('_', ' ')
}

export default function ExecutionTimeline({ state, onSelectEvent }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (state.autoFollow && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight }, [state.events.length, state.autoFollow])
  return <section className="timeline-panel">
    <div className="timeline-heading"><div><span className="timeline-icon"><Clock3 size={14} /></span><strong>Execution timeline</strong><span className="timeline-subtitle">Auditable event stream</span></div><div className="timeline-count">{state.events.length} EVENTS <span /> ITERATION {state.iteration}</div></div>
    <div className="timeline-scroll" ref={scrollRef}>{state.events.length ? <div className="timeline-list">{state.events.map((event, index) => <button className={`timeline-item ${state.selectedEventId === event.eventId ? 'selected' : ''} ${event.category?.toLowerCase() ?? ''}`} key={event.eventId} onClick={() => onSelectEvent(event.eventId)}>
      <span className="timeline-time">{time(index)}</span><span className="timeline-mark">{iconFor(event)}</span><span className="timeline-text">{titleFor(event)}</span><span className="timeline-event-node">{event.nodeId.replaceAll('_', ' ')}</span><span className="timeline-iteration">I{event.iteration}</span>
    </button>)}</div> : <div className="timeline-empty"><span className="empty-pulse" /><div><strong>Execution events will appear here</strong><span>Run a synthetic case to follow its decisions in real time.</span></div></div>}</div>
    <div className="timeline-foot"><span>All timestamps synthetic · click an event to inspect its node</span><span><Circle size={7} fill="currentColor" /> STREAMING STRUCTURED EVENTS</span></div>
  </section>
}
