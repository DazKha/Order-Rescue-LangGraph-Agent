import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, ArrowDownRight, Check, ChevronDown, Clock3, Copy, FileJson2, Info, LockKeyhole, MessageCircle, Send, ShieldAlert } from 'lucide-react'
import type { ExecutionEvent, ExecutionViewState, ReasoningCategory } from '../domain/types'
import StateDiff from './StateDiff'

const titles: Record<string, string> = {
  event_trigger: 'Event Trigger', load_case_state: 'Load Case State', evidence_builder: 'Evidence Builder', assess_case: 'AI Assessment', information_planner: 'Information-Seeking Planner', contact_policy_gate: 'Contact Policy Gate', buyer_question_generator: 'Buyer Question Generator', simulated_buyer_contact: 'Simulated Buyer Contact', waiting_for_buyer: 'WAITING_FOR_BUYER', buyer_reply_parser: 'Buyer Reply Parser', recovery_proposal: 'Recovery Action Proposal', recovery_policy_gate: 'Recovery Policy Gate', decision_router: 'Decision Router', recommendation_output: 'Recommendation Output', audit_logger: 'Audit Logger',
}
const categoryIcon: Record<ReasoningCategory, string> = { OBSERVATION: 'OBSERVE', HYPOTHESIS: 'HYPOTHESIS', UNCERTAINTY: 'MISSING INFO', CONFIDENCE: 'CONFIDENCE', DECISION: 'DECISION', POLICY: 'POLICY', RESULT: 'RESULT' }
const pretty = (value: unknown) => JSON.stringify(value ?? {}, null, 2)
interface Props { state: ExecutionViewState; onReply: (reply: string) => void; onTimeout: () => void; onClearDisruption: () => void }

export default function Inspector({ state, onReply, onTimeout, onClearDisruption }: Props) {
  const [tab, setTab] = useState<'Overview' | 'Input' | 'Output' | 'Trace'>('Overview')
  const [reply, setReply] = useState('Hôm qua mình đi làm nên không nghe máy. Mình vẫn muốn nhận hàng.')
  const [iteration, setIteration] = useState(state.iteration)
  useEffect(() => { setIteration(state.iteration) }, [state.iteration])
  useEffect(() => { setReply(state.caseId === 'CASE-003' ? 'Tòa nhà màu xanh, đối diện trường tiểu học.' : 'Hôm qua mình đi làm nên không nghe máy. Mình vẫn muốn nhận hàng.') }, [state.caseId])
  const selectedNode = state.nodes[state.selectedNodeId]
  const selectedEvent = state.events.find((event) => event.eventId === state.selectedEventId)
  const trace = selectedNode?.iterations[iteration] ?? []
  const lastAssessment = useMemo(() => [...(state.nodes.assess_case?.events ?? [])].reverse().find((event) => event.eventType === 'NODE_COMPLETED'), [state.nodes.assess_case?.events])
  const before = state.snapshots[0]
  const after = state.snapshots[state.snapshots.length - 1]
  const isWaiting = state.status === 'WAITING_FOR_BUYER'
  const currentTitle = titles[state.selectedNodeId] ?? state.selectedNodeId

  return <aside className="inspector-panel">
    <div className="inspector-header"><div><span className="eyebrow">NODE INSPECTOR</span><h2>{currentTitle}</h2></div><span className={`inspector-status status-${(selectedNode?.status ?? 'PENDING').toLowerCase()}`}><i />{selectedNode?.status ?? 'PENDING'}</span></div>
    <div className="inspector-tabs">{(['Overview', 'Input', 'Output', 'Trace'] as const).map((name) => <button className={tab === name ? 'active' : ''} onClick={() => setTab(name)} key={name}>{name}{name === 'Trace' && selectedNode?.events.length ? <span>{selectedNode.events.length}</span> : null}</button>)}</div>
    <div className="inspector-scroll">
      {isWaiting && <section className="buyer-card">
        <div className="buyer-card-top"><div className="buyer-card-icon"><MessageCircle size={15} /></div><div><strong>Simulated buyer contact</strong><span>External input required · no message sent</span></div><span className="waiting-pill"><i /> WAITING</span></div>
        <div className="outgoing-question"><span className="micro-label">QUESTION PREVIEW</span><p>{state.caseId === 'CASE-003' ? 'Bạn có thể cho biết địa điểm dễ nhận biết gần địa chỉ không?' : 'Bạn vẫn muốn nhận đơn hàng này chứ?'}</p></div>
        <label className="micro-label reply-label" htmlFor="buyer-reply">BUYER REPLY · SIMULATED</label>
        <textarea id="buyer-reply" rows={3} value={reply} onChange={(event) => setReply(event.target.value)} />
        <div className="buyer-actions"><button className="button-primary send-reply" onClick={() => onReply(reply)}><Send size={12} /> Submit reply</button>{state.caseId === 'CASE-002' && <button className="quiet-button" onClick={onTimeout}>Simulate timeout</button>}</div>
      </section>}

      {state.caseId === 'CASE-004' && state.caseState.disruptionActive && <section className="buyer-card disruption-card"><div className="buyer-card-top"><div className="buyer-card-icon"><Activity size={15} /></div><div><strong>Operational signal</strong><span>Synthetic depot disruption is active</span></div></div><p className="disruption-copy">The agent is holding the case without assigning blame to the buyer.</p><button className="button-primary send-reply" onClick={onClearDisruption}><Check size={12} /> Clear simulated disruption</button></section>}

      {tab === 'Overview' && <>
        <section className="inspector-block"><div className="block-label"><Info size={13} /> NODE SUMMARY</div><p className="node-description">{selectedEvent?.summary ?? selectedEvent?.content ?? selectedNode?.summary ?? 'Select a node or run the case to inspect its execution.'}</p>
          <div className="summary-meta"><span><Clock3 size={12} /> {selectedNode?.durationMs ? `${selectedNode.durationMs} ms` : '—'}</span><span><Activity size={12} /> Iteration {iteration}</span></div></section>
        <section className="inspector-block"><div className="block-label"><FileJson2 size={13} /> CURRENT CASE STATE</div><div className="state-grid"><div><span>Hypothesis</span><strong>{state.caseState.hypothesis.replaceAll('_', ' ')}</strong></div><div><span>Confidence</span><strong className={`confidence-${state.caseState.confidence.toLowerCase()}`}>{state.caseState.confidence}</strong></div><div><span>Buyer intent</span><strong>{state.caseState.buyerIntent.replaceAll('_', ' ')}</strong></div><div><span>Action eligibility</span><strong>{state.caseState.policyResult ?? 'NOT EVALUATED'}</strong></div>{state.caseState.recommendation && <div className="state-recommendation"><span>Final recommendation</span><strong>{state.caseState.recommendation.replaceAll('_', ' ')}</strong></div>}</div></section>
        {selectedNode?.events.some((item) => item.policy) && <PolicyTrace events={selectedNode.events} />}
        <section className="inspector-block evidence-block"><div className="block-label"><ArrowDownRight size={13} /> EVIDENCE REFERENCES</div>{state.caseState.evidence.map((evidence) => <div className="evidence-ref" key={evidence.id}><span className="evidence-id">{evidence.id}</span><span><strong>{evidence.label}</strong><small>{evidence.detail}</small></span></div>)}</section>
        <StateDiff before={before} after={after} />
        <section className="decision-summary"><span className="block-label"><Check size={13} /> DECISION SUMMARY</span><p>{lastAssessment?.summary ?? 'Run the case to see evidence-grounded decision updates.'}</p></section>
      </>}
      {tab === 'Input' && <section className="inspector-block json-panel"><div className="block-label"><FileJson2 size={13} /> NODE INPUT</div><pre>{pretty(selectedEvent?.input ?? selectedNode?.input ?? { case_id: state.caseId, state: state.caseState.workflowStatus })}</pre></section>}
      {tab === 'Output' && <section className="inspector-block json-panel"><div className="block-label"><FileJson2 size={13} /> STRUCTURED OUTPUT</div><pre>{pretty(selectedEvent?.output ?? selectedNode?.output ?? { status: selectedNode?.status ?? 'PENDING' })}</pre></section>}
      {tab === 'Trace' && <>
        <div className="iteration-select"><span>EXECUTION ITERATION</span><select value={iteration} onChange={(event) => setIteration(Number(event.target.value))}>{Array.from({ length: state.iteration }, (_, index) => <option key={index + 1} value={index + 1}>Iteration {index + 1}</option>)}</select><ChevronDown size={12} /></div>
        <div className="reasoning-stream">{trace.length ? trace.map((event) => <ReasoningEvent event={event} key={event.eventId} selected={event.eventId === selectedEvent?.eventId} />) : <div className="trace-empty"><Activity size={16} /><span>No trace events for this iteration yet.</span></div>}</div>
      </>}
    </div>
    <div className="inspector-footer"><span><ShieldAlert size={12} /> EXPLAINABLE OUTPUT ONLY</span><button title="Copy selected event JSON" onClick={() => navigator.clipboard?.writeText(pretty(selectedEvent ?? selectedNode ?? {}))}><Copy size={12} /> Copy trace</button></div>
  </aside>
}

function ReasoningEvent({ event, selected }: { event: ExecutionEvent; selected: boolean }) {
  return <article className={`reasoning-event ${event.category?.toLowerCase() ?? 'observation'} ${selected ? 'selected' : ''}`}><div className="reasoning-event-head"><span>{categoryIcon[event.category ?? 'OBSERVATION']}</span><time>{new Date(event.timestamp).toLocaleTimeString([], { minute: '2-digit', second: '2-digit' })}</time></div><p>{event.content ?? event.summary ?? event.eventType.replaceAll('_', ' ').toLowerCase()}</p>
    {event.evidenceRefs?.length ? <div className="reference-tags">{event.evidenceRefs.map((ref) => <span key={ref}>{ref}</span>)}</div> : null}
    {event.policy?.rules?.length ? <div className="rule-list">{event.policy.rules.map((rule) => <div className="rule-row" key={rule.ruleId}><span className={`rule-result ${rule.result.toLowerCase()}`}>{rule.result === 'PASS' ? <Check size={10} /> : <AlertTriangle size={10} />}</span><span className="rule-id">{rule.ruleId}</span><span className="rule-text">{rule.description}<small>{rule.detail}</small></span></div>)}<div className={`policy-final ${event.policy.decision.toLowerCase()}`}>FINAL · {event.policy.decision} <small>{event.policy.version}</small></div></div> : null}
  </article>
}

function PolicyTrace({ events }: { events: ExecutionEvent[] }) {
  const policyEvent = [...events].reverse().find((event) => event.policy)
  if (!policyEvent?.policy) return null
  return <section className="inspector-block policy-block"><div className="block-label"><LockKeyhole size={13} /> POLICY EVALUATION <span className="policy-version">{policyEvent.policy.version}</span></div>{policyEvent.policy.rules.map((rule) => <div className="policy-compact" key={rule.ruleId}><span className={`policy-check ${rule.result.toLowerCase()}`}>{rule.result === 'PASS' ? <Check size={10} /> : <AlertTriangle size={10} />}</span><div><strong>{rule.ruleId} · {rule.description}</strong><small>{rule.evaluatedInput} — {rule.detail}</small></div></div>)}<div className={`policy-decision ${policyEvent.policy.decision.toLowerCase()}`}>FINAL: {policyEvent.policy.decision}{policyEvent.policy.triggeringRuleIds.length ? ` · ${policyEvent.policy.triggeringRuleIds.join(', ')}` : ''}</div></section>
}
