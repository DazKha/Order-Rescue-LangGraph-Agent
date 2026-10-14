import { getInitialCase } from '../domain/cases'
import type { CaseId, ExecutionEvent, ExecutionViewState, NodeExecution, NodeStatus, Speed } from '../domain/types'

export const initialViewState = (caseId: CaseId): ExecutionViewState => ({
  caseId, iteration: 1, status: 'IDLE', nodes: {}, events: [], selectedNodeId: 'event_trigger', snapshots: [getInitialCase(caseId)], caseState: getInitialCase(caseId), speed: '1x', autoFollow: true,
})

export type Action = { type: 'EVENT'; event: ExecutionEvent } | { type: 'RESET'; caseId: CaseId } | { type: 'CASE'; caseId: CaseId } | { type: 'SELECT_NODE'; nodeId: string } | { type: 'SELECT_EVENT'; eventId: string } | { type: 'SPEED'; speed: Speed } | { type: 'AUTO_FOLLOW'; value: boolean } | { type: 'CONTROL'; status: 'PAUSED' | 'RUNNING' }

const terminalStatus = (state: ExecutionViewState, event: ExecutionEvent) => {
  if (event.eventType === 'STATE_TRANSITION' && event.snapshot) return event.snapshot.workflowStatus
  if (event.eventType === 'STATE_TRANSITION' && event.output && typeof event.output === 'object' && 'state' in event.output) return (event.output as { state: ExecutionViewState['status'] }).state
  if (event.status === 'WAITING') return 'WAITING_FOR_BUYER'
  if (event.status === 'ESCALATED') return 'ESCALATED'
  if (event.status === 'BLOCKED') return 'BLOCKED'
  if (state.status === 'PAUSED') return 'PAUSED'
  if (event.eventType === 'NODE_STARTED') return 'RUNNING'
  return state.status === 'IDLE' ? 'RUNNING' : state.status
}

export function executionReducer(state: ExecutionViewState, action: Action): ExecutionViewState {
  if (action.type === 'RESET' || action.type === 'CASE') return initialViewState(action.caseId)
  if (action.type === 'SELECT_NODE') return { ...state, selectedNodeId: action.nodeId, selectedEventId: undefined }
  if (action.type === 'SELECT_EVENT') {
    const event = state.events.find((item) => item.eventId === action.eventId)
    return { ...state, selectedEventId: action.eventId, selectedNodeId: event?.nodeId ?? state.selectedNodeId, iteration: event?.iteration ?? state.iteration }
  }
  if (action.type === 'SPEED') return { ...state, speed: action.speed }
  if (action.type === 'AUTO_FOLLOW') return { ...state, autoFollow: action.value }
  if (action.type === 'CONTROL') return { ...state, status: action.status }
  const event = action.event
  const oldNode: NodeExecution = state.nodes[event.nodeId] ?? { status: 'PENDING', events: [], iterations: {} }
  const status: NodeStatus = event.status ?? (event.eventType === 'NODE_STARTED' ? 'RUNNING' : event.eventType === 'NODE_COMPLETED' ? 'COMPLETED' : oldNode.status)
  const nodeEvents = [...oldNode.events, event]
  const iterationEvents = [...(oldNode.iterations[event.iteration] ?? []), event]
  const node: NodeExecution = { ...oldNode, status, durationMs: event.durationMs ?? oldNode.durationMs, summary: event.summary ?? (event.category ? event.content : oldNode.summary), input: event.input ?? oldNode.input, output: event.output ?? oldNode.output, events: nodeEvents, iterations: { ...oldNode.iterations, [event.iteration]: iterationEvents } }
  const snapshots = event.snapshot ? [...state.snapshots.filter((item) => item.caseId !== event.snapshot!.caseId || item.lastUpdated !== event.snapshot!.lastUpdated || item.workflowStatus !== event.snapshot!.workflowStatus), event.snapshot] : state.snapshots
  return {
    ...state, runId: event.runId, iteration: Math.max(state.iteration, event.iteration), status: terminalStatus(state, event),
    nodes: { ...state.nodes, [event.nodeId]: node }, events: [...state.events, event], selectedNodeId: state.autoFollow ? event.nodeId : state.selectedNodeId,
    selectedEventId: state.autoFollow ? event.eventId : state.selectedEventId, snapshots, caseState: event.snapshot ?? state.caseState,
  }
}
