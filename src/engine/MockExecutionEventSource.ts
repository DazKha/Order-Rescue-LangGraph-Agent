import { getInitialCase } from '../domain/cases'
import { evaluateContactPolicy, evaluateRecoveryPolicy } from '../domain/policy'
import type { CaseId, CaseState, ExecutionEvent, ExecutionEventSource, ExecutionEventType, PolicyEvaluation, Speed } from '../domain/types'

type EventDraft = Omit<ExecutionEvent, 'eventId' | 'runId' | 'caseId' | 'iteration' | 'timestamp'>
const speedDelay: Record<Speed, number> = { '0.5x': 1500, '1x': 760, '2x': 380, Instant: 0 }

export class MockExecutionEventSource implements ExecutionEventSource {
  private listeners = new Set<(event: ExecutionEvent) => void>()
  private queue: Array<() => EventDraft> = []
  private states = new Map<CaseId, CaseState>()
  private paused = false
  private draining = false
  private stepBudget = 0
  private speed: Speed = '1x'
  private runCounter = 0
  private eventCounter = 0
  private generation = 0
  private runId = ''
  private caseId: CaseId = 'CASE-001'
  private iteration = 1

  subscribe(listener: (event: ExecutionEvent) => void) { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  getCaseState(caseId: CaseId) { return structuredClone(this.states.get(caseId) ?? getInitialCase(caseId)) }
  setSpeed(speed: Speed) { this.speed = speed }
  pause() { this.paused = true }
  resume() { this.paused = false; this.stepBudget = 0; void this.drain() }
  step() { this.paused = true; this.stepBudget += 1; void this.drain() }
  reset(caseId: CaseId) {
    this.generation += 1; this.paused = true; this.stepBudget = 0; this.queue = []; this.draining = false
    const state = getInitialCase(caseId); this.states.set(caseId, state)
    this.caseId = caseId; this.iteration = 1; this.runId = ''
  }

  startCase(caseId: CaseId) {
    this.reset(caseId); this.caseId = caseId; this.iteration = 1
    this.runId = `RUN-${String(++this.runCounter).padStart(3, '0')}`
    this.paused = false
    const s = this.state()
    if (caseId === 'CASE-001' || caseId === 'CASE-002') this.buildUnavailabilityFlow(s)
    if (caseId === 'CASE-003') this.buildAddressFlow(s)
    if (caseId === 'CASE-004') this.buildDisruptionFlow(s)
    if (caseId === 'CASE-005') this.buildRefusalFlow(s)
    void this.drain()
  }

  submitBuyerReply(reply: string) {
    if (this.state().workflowStatus !== 'WAITING_FOR_BUYER') return
    const before = this.state()
    this.iteration = 2
    this.state({ ...before, workflowStatus: 'RUNNING' })
    if (this.caseId === 'CASE-003') {
      this.handleLandmarkReply(reply, before)
      void this.drain()
      return
    }
    const wants = /want|still|receive|nhận|muốn|giao/i.test(reply)
    const intent = wants ? 'WANTS_DELIVERY' : /don't|không muốn|khong muon|cancel|hủy|huy/i.test(reply) ? 'DOES_NOT_WANT_DELIVERY' : 'UNKNOWN'
    const newEvidence = { id: 'EVID-003', label: 'Buyer reply', detail: reply, source: 'Simulated buyer response', timestamp: new Date().toISOString() }
    const after: CaseState = { ...before, buyerIntent: intent, confidence: intent === 'UNKNOWN' ? 'MEDIUM' : 'HIGH', missingInformation: intent === 'UNKNOWN' ? ['buyer_intent'] : [], proposedAction: intent === 'WANTS_DELIVERY' ? 'RECOMMEND_STANDARD_RETRY' : intent === 'DOES_NOT_WANT_DELIVERY' ? 'ESCALATE_TO_HUMAN' : 'WAIT_FOR_CLARIFICATION', evidence: [...before.evidence, newEvidence], workflowStatus: 'RUNNING', lastUpdated: 'Just now' }
    this.state(after)
    this.queue.push(
      () => this.draft('buyer_reply_parser', 'NODE_STARTED', { status: 'RUNNING', input: { reply } }),
      () => this.draft('buyer_reply_parser', 'BUYER_REPLY', { category: 'OBSERVATION', content: 'A simulated buyer response was received.', input: { reply }, output: { buyer_intent: intent }, evidenceRefs: [newEvidence.id], summary: 'Buyer response parsed into structured evidence.' }),
      () => this.draft('buyer_reply_parser', 'NODE_COMPLETED', { status: 'COMPLETED', output: { buyer_intent: intent }, summary: 'Buyer intent extracted from the simulated reply.' }),
      () => this.draft('evidence_builder', 'NODE_STARTED', { status: 'RUNNING', input: { evidence_count: before.evidence.length }, summary: 'Updating evidence pack with buyer reply.' }),
      () => this.draft('evidence_builder', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: `Buyer reply: “${reply}”`, evidenceRefs: [newEvidence.id], output: { evidence_count: after.evidence.length } }),
      () => this.draft('evidence_builder', 'NODE_COMPLETED', { status: 'COMPLETED', durationMs: 180, output: { evidence: after.evidence }, summary: 'Evidence pack now includes the buyer response.' }),
      () => this.draft('assess_case', 'NODE_STARTED', { status: 'RUNNING', input: { evidence: after.evidence }, summary: 'Reassessing with iteration 2 evidence.' }),
      () => this.draft('assess_case', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: intent === 'WANTS_DELIVERY' ? 'Buyer says they still want the parcel.' : intent === 'DOES_NOT_WANT_DELIVERY' ? 'Buyer says they do not want delivery.' : 'Reply does not clearly state buyer intent.', evidenceRefs: [newEvidence.id] }),
      () => this.draft('assess_case', 'HYPOTHESIS_UPDATED', { category: 'HYPOTHESIS', content: 'Temporary unavailability remains the best-supported explanation.', evidenceRefs: ['EVID-001', 'EVID-002', newEvidence.id], output: { hypothesis: 'TEMPORARY_UNAVAILABILITY' } }),
      () => this.draft('assess_case', 'CONFIDENCE_UPDATED', { category: 'CONFIDENCE', content: `Confidence updated: LOW → ${after.confidence}.`, output: { previous: 'LOW', current: after.confidence } }),
      () => this.draft('assess_case', 'MISSING_INFORMATION_IDENTIFIED', { category: 'UNCERTAINTY', content: intent === 'UNKNOWN' ? 'Buyer intent remains unclear.' : 'No decision-critical information is missing.', output: { missing_information: after.missingInformation } }),
      () => this.draft('assess_case', 'NODE_COMPLETED', { status: 'COMPLETED', durationMs: 840, input: { evidence_refs: after.evidence.map((e) => e.id) }, output: { hypothesis: after.hypothesis, confidence: after.confidence, buyer_intent: intent, missing_information: after.missingInformation }, summary: 'Buyer intent now changes the recovery recommendation.', snapshot: after, previousState: { buyerIntent: before.buyerIntent, confidence: before.confidence, proposedAction: 'NEED_CONFIRMATION' }, updatedState: { buyerIntent: intent, confidence: after.confidence, proposedAction: after.proposedAction } }),
      () => this.draft('information_planner', 'NODE_STARTED', { status: 'RUNNING', input: { missing_information: after.missingInformation, buyer_intent: intent } }),
      () => this.draft('information_planner', 'DECISION_PROPOSED', { category: 'DECISION', content: intent === 'UNKNOWN' ? 'Ask one follow-up because buyer intent remains unresolved.' : 'No further buyer information is needed; intent is established.', output: { decision: intent === 'UNKNOWN' ? 'ASK_BUYER' : 'DO_NOT_ASK' } }),
      () => this.draft('information_planner', 'NODE_COMPLETED', { status: 'COMPLETED', durationMs: 120, output: { decision: 'PROCEED_TO_RECOVERY', potential_action_impact: 'buyer intent changes retry eligibility' }, summary: 'New evidence supports a recovery proposal.' }),
    )
    if (intent === 'WANTS_DELIVERY') this.buildPermittedRetry(after)
    else if (intent === 'DOES_NOT_WANT_DELIVERY') this.buildEscalation(after, 'Buyer does not want delivery; route for human handling.')
    else this.buildWaitRecommendation(after)
    void this.drain()
  }

  private handleLandmarkReply(reply: string, before: CaseState) {
    const landmark = { id: 'EVID-032', label: 'Buyer landmark clarification', detail: reply, source: 'Simulated buyer response', timestamp: new Date().toISOString() }
    const assessed = { ...before, addressLandmark: reply, missingInformation: [], confidence: 'HIGH' as const, proposedAction: 'MODIFY_SHIPMENT_ADDRESS', evidence: [...before.evidence, landmark], workflowStatus: 'RUNNING' as const }
    this.state(assessed)
    this.queue.push(
      () => this.draft('buyer_reply_parser', 'NODE_STARTED', { status: 'RUNNING', input: { reply } }),
      () => this.draft('buyer_reply_parser', 'BUYER_REPLY', { category: 'OBSERVATION', content: 'Buyer supplied a landmark clarification.', input: { reply }, output: { address_landmark: reply }, evidenceRefs: [landmark.id] }),
      () => this.draft('buyer_reply_parser', 'NODE_COMPLETED', { status: 'COMPLETED', output: { address_landmark: reply }, summary: 'Landmark clarification extracted from the simulated reply.' }),
      () => this.draft('evidence_builder', 'NODE_STARTED', { status: 'RUNNING', input: { evidence_count: before.evidence.length } }),
      () => this.draft('evidence_builder', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: `Buyer provided landmark details: “${reply}”`, evidenceRefs: [landmark.id] }),
      () => this.draft('evidence_builder', 'NODE_COMPLETED', { status: 'COMPLETED', output: { evidence: assessed.evidence }, summary: 'Evidence pack includes the buyer’s landmark clarification.' }),
      () => this.draft('assess_case', 'NODE_STARTED', { status: 'RUNNING', input: { evidence: assessed.evidence } }),
      () => this.draft('assess_case', 'HYPOTHESIS_UPDATED', { category: 'HYPOTHESIS', content: 'Address ambiguity is clarified; an address update is still outside agent authority.', evidenceRefs: [landmark.id] }),
      () => this.draft('assess_case', 'NODE_COMPLETED', { status: 'COMPLETED', output: { hypothesis: 'INSUFFICIENT_ADDRESS_DETAIL', confidence: 'HIGH', missing_information: [] }, summary: 'Clarification is sufficient for a human-approved address handling step.', snapshot: assessed }),
      () => this.draft('recovery_proposal', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Propose applying the clarified address through an approved human-handling flow.', output: { proposed_action: 'MODIFY_SHIPMENT_ADDRESS' }, evidenceRefs: [landmark.id] }),
    )
    const policy = evaluateRecoveryPolicy(assessed)
    this.pushPolicy('recovery_policy_gate', policy, 'Autonomous shipment-address modification is blocked by agent authority.')
    this.buildEscalation({ ...assessed, policyResult: policy.decision }, 'Address clarification is captured; a human must approve any shipment-address change.')
  }

  submitTimeout() {
    if (this.state().workflowStatus !== 'WAITING_FOR_BUYER') return
    const state = this.state()
    this.iteration = 2
    this.queue.push(
      () => this.draft('buyer_reply_parser', 'TIMEOUT', { category: 'UNCERTAINTY', content: 'No buyer response arrived before the simulated timeout.', summary: 'Silence does not establish refusal.' }),
      () => this.draft('decision_router', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Wait for another permitted signal; do not return the parcel automatically.', output: { recommendation: 'WAIT_FOR_BUYER' } }),
      () => this.draft('recommendation_output', 'NODE_COMPLETED', { status: 'COMPLETED', output: { recommendation: 'WAIT_FOR_BUYER' }, summary: 'No reply is not treated as refusal.' }),
      () => this.draft('audit_logger', 'NODE_COMPLETED', { status: 'COMPLETED', input: { buyer_reply: 'timeout', policy: 'DEMO-POLICY-1.0' }, output: { recommendation: 'WAIT_FOR_BUYER', automatic_return: false }, summary: 'Timeout recorded without inferring buyer refusal.' }),
    )
    this.publish({ ...state, workflowStatus: 'COMPLETED', recommendation: 'WAIT_FOR_BUYER', proposedAction: 'WAIT_FOR_BUYER' }, state, 'recommendation_output')
    void this.drain()
  }

  clearDisruption() {
    if (this.caseId !== 'CASE-004' || !this.state().disruptionActive) return
    const before = this.state()
    this.iteration = 2
    const after = { ...before, disruptionActive: false, hypothesis: 'DELIVERY_DELAY', confidence: 'MEDIUM' as const, missingInformation: ['next_route_status'], proposedAction: 'HOLD_AND_REASSESS', evidence: [...before.evidence, { id: 'EVID-042', label: 'Disruption cleared', detail: 'Synthetic depot disruption has cleared.', source: 'Synthetic operations event', timestamp: new Date().toISOString() }], workflowStatus: 'RUNNING' as const }
    this.state(after)
    this.queue.push(
      () => this.draft('event_trigger', 'DISRUPTION_CLEARED', { category: 'OBSERVATION', content: 'The synthetic depot disruption has cleared.', evidenceRefs: ['EVID-042'] }),
      () => this.draft('evidence_builder', 'NODE_COMPLETED', { status: 'COMPLETED', output: { disruption_active: false }, summary: 'Evidence pack updated with disruption clearance.' }),
      () => this.draft('assess_case', 'NODE_STARTED', { status: 'RUNNING', input: { evidence: after.evidence } }),
      () => this.draft('assess_case', 'HYPOTHESIS_UPDATED', { category: 'HYPOTHESIS', content: 'Service disruption has cleared; route status is still needed.', evidenceRefs: ['EVID-041', 'EVID-042'] }),
      () => this.draft('assess_case', 'NODE_COMPLETED', { status: 'COMPLETED', durationMs: 620, output: { hypothesis: after.hypothesis, confidence: after.confidence }, summary: 'Reassessment keeps delivery on hold until route status is known.', snapshot: after }),
      () => this.draft('recommendation_output', 'NODE_COMPLETED', { status: 'COMPLETED', output: { recommendation: 'HOLD_AND_REASSESS' }, summary: 'Continue holding and reassess after route status arrives.' }),
      () => this.draft('audit_logger', 'NODE_COMPLETED', { status: 'COMPLETED', evidenceRefs: after.evidence.map((item) => item.id), input: { disruption_active: true }, output: { recommendation: 'HOLD_AND_REASSESS', disruption_active: false }, summary: 'Disruption-clear reassessment recorded with the new evidence.' }),
    )
    this.publish({ ...after, workflowStatus: 'COMPLETED', recommendation: 'HOLD_AND_REASSESS' }, before, 'recommendation_output')
    void this.drain()
  }

  private buildUnavailabilityFlow(s: CaseState) {
    this.queue.push(
      () => this.draft('event_trigger', 'NODE_COMPLETED', { status: 'COMPLETED', output: { event: 'DELIVERY_FAILED' }, summary: 'Delivery failure event received.' }),
      () => this.draft('load_case_state', 'NODE_COMPLETED', { status: 'COMPLETED', output: s, summary: 'Loaded current case state.' }),
      () => this.draft('evidence_builder', 'NODE_STARTED', { status: 'RUNNING', input: { courier_note: s.courierNote, attempt_count: s.attemptCount } }),
      () => this.draft('evidence_builder', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: `Delivery status: ${s.deliveryStatus}.`, evidenceRefs: s.evidence.map((e) => e.id) }),
      () => this.draft('evidence_builder', 'NODE_COMPLETED', { status: 'COMPLETED', durationMs: 260, output: { evidence: s.evidence }, summary: 'Courier facts normalized into an evidence pack.' }),
      () => this.draft('assess_case', 'NODE_STARTED', { status: 'RUNNING', input: { evidence: s.evidence } }),
      () => this.draft('assess_case', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: `Courier note: ${s.courierNote}`, evidenceRefs: s.evidence.map((e) => e.id) }),
      () => this.draft('assess_case', 'HYPOTHESIS_UPDATED', { category: 'HYPOTHESIS', content: 'Temporary unavailability is a plausible cause.', evidenceRefs: s.evidence.map((e) => e.id) }),
      () => this.draft('assess_case', 'CONFIDENCE_UPDATED', { category: 'CONFIDENCE', content: 'LOW — buyer intent is not confirmed.', output: { confidence: 'LOW' } }),
      () => this.draft('assess_case', 'MISSING_INFORMATION_IDENTIFIED', { category: 'UNCERTAINTY', content: 'Missing information: whether the buyer still wants delivery.', output: { missing_information: ['buyer_intent'] } }),
      () => this.draft('assess_case', 'NODE_COMPLETED', { status: 'COMPLETED', durationMs: 840, output: { hypothesis: 'TEMPORARY_UNAVAILABILITY', confidence: 'LOW', missing_information: ['buyer_intent'] }, summary: 'Buyer intent remains unknown; temporary unavailability is unconfirmed.' }),
      () => this.draft('information_planner', 'NODE_STARTED', { status: 'RUNNING', input: { missing_information: ['buyer_intent'], return_state: s.returnState } }),
      () => this.draft('information_planner', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Buyer confirmation could change the retry recommendation.', output: { decision: 'ASK_BUYER', impact: 'retry eligibility changes when intent is known' } }),
      () => this.draft('information_planner', 'NODE_COMPLETED', { status: 'COMPLETED', durationMs: 180, output: { decision: 'ASK_BUYER', reason: 'Buyer intent is unresolved and recovery is eligible.' }, summary: 'Buyer confirmation could change the next action.' }),
    )
    const policy = evaluateContactPolicy(s)
    this.pushPolicy('contact_policy_gate', policy, 'One clarification request is permitted under demo policy.')
    if (policy.decision === 'PERMITTED') {
      this.queue.push(
        () => this.draft('buyer_question_generator', 'NODE_COMPLETED', { status: 'COMPLETED', output: { question: 'Bạn vẫn muốn nhận đơn hàng này chứ?' }, summary: 'Generated one concise question about buyer intent.' }),
        () => this.draft('simulated_buyer_contact', 'NODE_COMPLETED', { status: 'COMPLETED', output: { outgoing_message: 'Bạn vẫn muốn nhận đơn hàng này chứ?', simulated: true }, summary: 'Question shown in the simulator; no real message was sent.' }),
        () => this.draft('waiting_for_buyer', 'STATE_TRANSITION', { status: 'WAITING', category: 'UNCERTAINTY', content: 'Execution paused while awaiting simulated buyer input.', output: { state: 'WAITING_FOR_BUYER' }, summary: 'Waiting for buyer response.' }),
      )
      this.state({ ...s, workflowStatus: 'WAITING_FOR_BUYER' })
    } else this.buildEscalation(s, 'Buyer contact is not permitted by demo policy.')
  }

  private buildAddressFlow(s: CaseState) {
    this.queue.push(
      () => this.draft('event_trigger', 'NODE_COMPLETED', { status: 'COMPLETED', output: { event: 'DELIVERY_FAILED' } }),
      () => this.draft('evidence_builder', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: 'Courier note indicates insufficient address detail.', evidenceRefs: ['EVID-031'] }),
      () => this.draft('assess_case', 'NODE_COMPLETED', { status: 'COMPLETED', output: { hypothesis: s.hypothesis, confidence: s.confidence, missing_information: ['address_landmark'] }, summary: 'A landmark is needed to clarify the address.' }),
      () => this.draft('information_planner', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Ask for a landmark; it can resolve delivery location ambiguity.', output: { decision: 'ASK_BUYER_FOR_LANDMARK' } }),
    )
    this.pushPolicy('contact_policy_gate', evaluateContactPolicy(s), 'Address clarification is permitted.')
    this.queue.push(
      () => this.draft('buyer_question_generator', 'NODE_COMPLETED', { status: 'COMPLETED', output: { question: 'Bạn có thể cho biết địa điểm dễ nhận biết gần địa chỉ không?' }, summary: 'Generated a landmark clarification question.' }),
      () => this.draft('waiting_for_buyer', 'STATE_TRANSITION', { status: 'WAITING', output: { state: 'WAITING_FOR_BUYER' }, summary: 'Waiting for landmark clarification.' }),
    )
    this.state({ ...s, workflowStatus: 'WAITING_FOR_BUYER' })
  }

  private buildDisruptionFlow(s: CaseState) {
    this.queue.push(
      () => this.draft('event_trigger', 'NODE_COMPLETED', { status: 'COMPLETED', output: { event: 'DELIVERY_FAILED', disruption_signal: true } }),
      () => this.draft('evidence_builder', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: 'Synthetic depot disruption is active; do not attribute delay to buyer.', evidenceRefs: ['EVID-041'] }),
      () => this.draft('assess_case', 'NODE_COMPLETED', { status: 'COMPLETED', output: { hypothesis: 'SERVICE_DISRUPTION', confidence: 'HIGH' }, summary: 'Operational disruption explains the current delay.' }),
      () => this.draft('recovery_proposal', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Recommend hold and reassess when the disruption clears.', output: { proposed_action: 'HOLD_AND_REASSESS' } }),
      () => this.draft('recovery_policy_gate', 'POLICY_DECISION', { category: 'POLICY', policy: evaluateRecoveryPolicy({ ...s, proposedAction: 'HOLD_AND_REASSESS' }), summary: 'Hold and reassess is permitted by demo policy.' }),
      () => this.draft('recommendation_output', 'NODE_COMPLETED', { status: 'COMPLETED', output: { recommendation: 'HOLD_AND_REASSESS', real_dispatch: false }, summary: 'Hold and reassess; no logistics action has been executed.' }),
    )
    this.publish({ ...s, workflowStatus: 'COMPLETED', recommendation: 'HOLD_AND_REASSESS', policyResult: 'PERMITTED' }, s, 'recommendation_output')
  }

  private buildRefusalFlow(s: CaseState) {
    this.queue.push(
      () => this.draft('event_trigger', 'NODE_COMPLETED', { status: 'COMPLETED', output: { event: 'DELIVERY_FAILED' } }),
      () => this.draft('evidence_builder', 'EVIDENCE_OBSERVED', { category: 'OBSERVATION', content: 'REFUSED status has no signature or supporting detail.', evidenceRefs: ['EVID-051'] }),
      () => this.draft('assess_case', 'HYPOTHESIS_UPDATED', { category: 'HYPOTHESIS', content: 'Intentional refusal is not verified by the available evidence.', evidenceRefs: ['EVID-051'] }),
      () => this.draft('assess_case', 'CONFIDENCE_UPDATED', { category: 'CONFIDENCE', content: 'LOW — refusal evidence is missing.', output: { confidence: 'LOW' } }),
      () => this.draft('recovery_proposal', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Automatic return was proposed by the raw status and will be checked against policy.', output: { proposed_action: 'AUTOMATIC_RETURN' } }),
    )
    const proposal = { ...s, proposedAction: 'AUTOMATIC_RETURN' }
    const policy = evaluateRecoveryPolicy(proposal)
    this.pushPolicy('recovery_policy_gate', policy, 'Unsupported refusal blocks automatic return and requires human review.')
    this.buildEscalation({ ...proposal, policyResult: policy.decision }, 'Refusal lacks supporting evidence; escalate to human.')
  }

  private buildPermittedRetry(state: CaseState) {
    const proposal = { ...state, proposedAction: 'RECOMMEND_STANDARD_RETRY' }
    this.queue.push(
      () => this.draft('recovery_proposal', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Buyer wants delivery and the attempt limit remains open; propose a standard retry.', output: { proposed_action: 'RECOMMEND_STANDARD_RETRY' }, evidenceRefs: ['EVID-003'] }),
    )
    const policy = evaluateRecoveryPolicy(proposal)
    this.pushPolicy('recovery_policy_gate', policy, 'Retry recommendation is permitted because the case remains eligible.')
    this.queue.push(
      () => this.draft('decision_router', 'NODE_COMPLETED', { status: 'COMPLETED', output: { route: 'PERMITTED' }, summary: 'Policy allows a recommendation only; no courier action is executed.' }),
      () => this.draft('recommendation_output', 'NODE_COMPLETED', { status: 'COMPLETED', category: 'RESULT', output: { recommendation: 'RECOMMEND_STANDARD_RETRY', policy_result: 'PERMITTED', real_dispatch: false }, summary: 'Recommend a standard retry. This is not a dispatch.' }),
      () => this.draft('audit_logger', 'NODE_COMPLETED', { status: 'COMPLETED', input: { previous_state: { buyer_intent: 'UNKNOWN', confidence: 'LOW' }, updated_state: { buyer_intent: 'WANTS_DELIVERY', confidence: 'HIGH' } }, output: { policy_version: policy.version, triggering_rule_ids: policy.triggeringRuleIds, recommendation: 'RECOMMEND_STANDARD_RETRY', evidence_refs: state.evidence.map((item) => item.id) }, evidenceRefs: state.evidence.map((item) => item.id), policy, summary: 'Recommendation, policy version, and evidence references recorded in the audit trail.' }),
    )
    this.publish({ ...proposal, workflowStatus: 'COMPLETED', recommendation: 'RECOMMEND_STANDARD_RETRY', policyResult: policy.decision }, this.state(), 'audit_logger', policy)
  }

  private buildWaitRecommendation(state: CaseState) {
    this.queue.push(() => this.draft('recovery_proposal', 'DECISION_PROPOSED', { category: 'DECISION', content: 'Wait for clearer buyer intent; current reply is ambiguous.', output: { proposed_action: 'WAIT_FOR_CLARIFICATION' } }))
    this.queue.push(() => this.draft('recommendation_output', 'NODE_COMPLETED', { status: 'COMPLETED', category: 'RESULT', output: { recommendation: 'WAIT_FOR_CLARIFICATION', policy_result: 'PERMITTED' }, summary: 'Wait for clarification; do not assume refusal.' }))
    this.publish({ ...state, workflowStatus: 'COMPLETED', proposedAction: 'WAIT_FOR_CLARIFICATION', recommendation: 'WAIT_FOR_CLARIFICATION', policyResult: 'PERMITTED' }, state, 'recommendation_output')
  }

  private buildEscalation(state: CaseState, reason: string) {
    this.queue.push(
      () => this.draft('decision_router', 'STATE_TRANSITION', { status: 'ESCALATED', category: 'DECISION', content: reason, output: { route: 'ESCALATE' } }),
      () => this.draft('recommendation_output', 'NODE_COMPLETED', { status: 'ESCALATED', category: 'RESULT', output: { recommendation: 'ESCALATE_TO_HUMAN', reason, real_dispatch: false }, summary: 'Case routed to human review.' }),
      () => this.draft('audit_logger', 'NODE_COMPLETED', { status: 'COMPLETED', input: { previous_state: { hypothesis: state.hypothesis, confidence: state.confidence }, policy_version: 'DEMO-POLICY-1.0' }, output: { recommendation: 'ESCALATE_TO_HUMAN', evidence_refs: state.evidence.map((e) => e.id) }, evidenceRefs: state.evidence.map((e) => e.id), summary: 'Escalation recorded with evidence references.' }),
    )
    this.publish({ ...state, workflowStatus: 'ESCALATED', recommendation: 'ESCALATE_TO_HUMAN', policyResult: state.policyResult ?? 'ESCALATE' }, state, 'audit_logger')
  }

  private pushPolicy(nodeId: string, policy: PolicyEvaluation, summary: string) {
    this.queue.push(() => this.draft(nodeId, 'POLICY_CHECK_STARTED', { category: 'POLICY', content: `Evaluating ${policy.version}.`, input: { policy_version: policy.version } }))
    for (const rule of policy.rules) this.queue.push(() => this.draft(nodeId, 'POLICY_RULE_EVALUATED', { category: 'POLICY', content: `[${rule.result}] ${rule.ruleId} · ${rule.description}`, output: rule, policy }))
    this.queue.push(() => this.draft(nodeId, 'POLICY_DECISION', { category: 'POLICY', status: policy.decision === 'PERMITTED' ? 'COMPLETED' : policy.decision === 'BLOCKED' ? 'BLOCKED' : 'ESCALATED', content: `Final policy decision: ${policy.decision}.`, policy, summary }))
  }

  private publish(finalState: CaseState, prior: CaseState, nodeId: string, policy?: PolicyEvaluation) {
    this.queue.push(() => this.draft(nodeId, 'STATE_TRANSITION', { category: 'RESULT', content: `Case state updated: ${finalState.workflowStatus}.`, previousState: { buyerIntent: prior.buyerIntent, confidence: prior.confidence, proposedAction: prior.proposedAction }, updatedState: { buyerIntent: finalState.buyerIntent, confidence: finalState.confidence, proposedAction: finalState.proposedAction, recommendation: finalState.recommendation }, snapshot: finalState, output: { state: finalState.workflowStatus, policy_decision: policy?.decision ?? finalState.policyResult } }))
    this.state(finalState)
  }

  private state(next?: CaseState) { if (next) this.states.set(this.caseId, next); return this.states.get(this.caseId) ?? getInitialCase(this.caseId) }
  private draft(nodeId: string, eventType: ExecutionEventType, rest: Omit<EventDraft, 'nodeId' | 'eventType'>): EventDraft { return { nodeId, eventType, ...rest } }

  private async drain() {
    if (this.draining) return
    this.draining = true
    const generation = this.generation
    while (generation === this.generation && this.queue.length && (!this.paused || this.stepBudget > 0)) {
      if (this.paused) this.stepBudget -= 1
      const draft = this.queue.shift()!()
      const event: ExecutionEvent = { ...draft, eventId: `EVT-${String(++this.eventCounter).padStart(4, '0')}`, runId: this.runId, caseId: this.caseId, iteration: this.iteration, timestamp: new Date().toISOString() }
      for (const listener of this.listeners) listener(event)
      const delay = speedDelay[this.speed]
      if (delay && this.queue.length && (!this.paused || this.stepBudget > 0)) await new Promise((resolve) => setTimeout(resolve, delay))
    }
    if (generation === this.generation) {
      this.draining = false
      if (!this.paused && this.queue.length) void this.drain()
    }
  }
}
