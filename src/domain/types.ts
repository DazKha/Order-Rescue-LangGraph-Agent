export type CaseId = 'CASE-001' | 'CASE-002' | 'CASE-003' | 'CASE-004' | 'CASE-005'
export type Confidence = 'LOW' | 'MEDIUM' | 'HIGH'
export type WorkflowStatus = 'IDLE' | 'RUNNING' | 'WAITING_FOR_BUYER' | 'COMPLETED' | 'BLOCKED' | 'ESCALATED' | 'PAUSED'
export type NodeStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'WAITING' | 'BLOCKED' | 'ESCALATED' | 'FAILED'
export type NodeKind = 'event' | 'process' | 'reasoning' | 'policy' | 'waiting' | 'router' | 'output'
export type Speed = '0.5x' | '1x' | '2x' | 'Instant'
export type ReasoningCategory = 'OBSERVATION' | 'HYPOTHESIS' | 'UNCERTAINTY' | 'CONFIDENCE' | 'DECISION' | 'POLICY' | 'RESULT'
export type ExecutionEventType = 'NODE_STARTED' | 'NODE_PROGRESS' | 'EVIDENCE_OBSERVED' | 'HYPOTHESIS_UPDATED' | 'CONFIDENCE_UPDATED' | 'MISSING_INFORMATION_IDENTIFIED' | 'INFORMATION_REQUEST_PROPOSED' | 'DECISION_PROPOSED' | 'POLICY_CHECK_STARTED' | 'POLICY_RULE_EVALUATED' | 'POLICY_DECISION' | 'STATE_TRANSITION' | 'NODE_COMPLETED' | 'NODE_FAILED' | 'BUYER_REPLY' | 'TIMEOUT' | 'DISRUPTION_CLEARED'

export interface Evidence { id: string; label: string; detail: string; source: string; timestamp: string }
export interface CaseState {
  caseId: CaseId
  scenario: string
  deliveryStatus: string
  courierNote: string
  attemptCount: number
  attemptLimit: number
  returnState: 'NOT_STARTED' | 'RETURN_STARTED'
  buyerIntent: 'UNKNOWN' | 'WANTS_DELIVERY' | 'DOES_NOT_WANT_DELIVERY'
  addressLandmark?: string
  disruptionActive?: boolean
  hypothesis: string
  confidence: Confidence
  missingInformation: string[]
  proposedAction: string
  policyResult?: 'PERMITTED' | 'BLOCKED' | 'ESCALATE'
  recommendation?: string
  evidence: Evidence[]
  workflowStatus: WorkflowStatus
  lastUpdated: string
}
export interface PolicyRule { ruleId: string; description: string; evaluatedInput: string; result: 'PASS' | 'FAIL'; detail: string }
export interface PolicyEvaluation { version: string; decision: 'PERMITTED' | 'BLOCKED' | 'ESCALATE'; rules: PolicyRule[]; triggeringRuleIds: string[] }
export interface ExecutionEvent {
  eventId: string
  runId: string
  caseId: CaseId
  iteration: number
  nodeId: string
  eventType: ExecutionEventType
  timestamp: string
  durationMs?: number
  category?: ReasoningCategory
  content?: string
  evidenceRefs?: string[]
  input?: unknown
  output?: unknown
  summary?: string
  status?: NodeStatus
  snapshot?: CaseState
  previousState?: Partial<CaseState>
  updatedState?: Partial<CaseState>
  policy?: PolicyEvaluation
  isFinal?: boolean
}
export interface NodeDefinition { id: string; label: string; kind: NodeKind; description: string }
export interface NodeExecution { status: NodeStatus; durationMs?: number; summary?: string; input?: unknown; output?: unknown; events: ExecutionEvent[]; iterations: Record<number, ExecutionEvent[]> }
export interface ExecutionEventSource {
  startCase(caseId: CaseId): void
  subscribe(listener: (event: ExecutionEvent) => void): () => void
  submitBuyerReply(reply: string): void
  submitTimeout(): void
  clearDisruption(): void
  resume(): void
  pause(): void
  step(): void
  setSpeed(speed: Speed): void
  reset(caseId: CaseId): void
  getCaseState(caseId: CaseId): CaseState
}
export interface TimelineEvent extends ExecutionEvent { selected?: boolean }
export interface ExecutionViewState {
  caseId: CaseId
  runId?: string
  iteration: number
  status: WorkflowStatus
  nodes: Record<string, NodeExecution>
  events: ExecutionEvent[]
  selectedNodeId: string
  selectedEventId?: string
  snapshots: CaseState[]
  caseState: CaseState
  speed: Speed
  autoFollow: boolean
}
