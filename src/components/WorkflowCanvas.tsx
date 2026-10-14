import { useEffect, useMemo, useState } from 'react'
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node, type NodeTypes, type ReactFlowInstance } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { ExecutionViewState, NodeDefinition } from '../domain/types'
import WorkflowNode, { type GraphNodeData } from './WorkflowNode'

const definitions: NodeDefinition[] = [
  { id: 'event_trigger', label: 'Event Trigger', kind: 'event', description: 'Receives DELIVERY_FAILED or BUYER_REPLY.' },
  { id: 'load_case_state', label: 'Load Case State', kind: 'process', description: 'Loads persisted synthetic case state.' },
  { id: 'evidence_builder', label: 'Evidence Builder', kind: 'process', description: 'Normalizes courier, buyer, and operations evidence.' },
  { id: 'assess_case', label: 'AI Assessment', kind: 'reasoning', description: 'Evaluates evidence, hypothesis, confidence, and uncertainty.' },
  { id: 'information_planner', label: 'Information Planner', kind: 'reasoning', description: 'Checks whether more information can change the next action.' },
  { id: 'contact_policy_gate', label: 'Contact Policy Gate', kind: 'policy', description: 'Deterministically checks whether buyer contact is allowed.' },
  { id: 'buyer_question_generator', label: 'Question Generator', kind: 'reasoning', description: 'Creates one concise clarification question.' },
  { id: 'simulated_buyer_contact', label: 'Simulated Contact', kind: 'event', description: 'Displays a synthetic outgoing message.' },
  { id: 'waiting_for_buyer', label: 'WAITING_FOR_BUYER', kind: 'waiting', description: 'Persists case state and pauses for external evidence.' },
  { id: 'buyer_reply_parser', label: 'Buyer Reply Parser', kind: 'process', description: 'Converts a simulated response into structured evidence.' },
  { id: 'recovery_proposal', label: 'Recovery Proposal', kind: 'reasoning', description: 'Proposes a recovery action from current evidence.' },
  { id: 'recovery_policy_gate', label: 'Recovery Policy Gate', kind: 'policy', description: 'Checks action authority, evidence, attempts, and deadline.' },
  { id: 'decision_router', label: 'Decision Router', kind: 'router', description: 'Routes permitted, blocked, or escalated decisions.' },
  { id: 'recommendation_output', label: 'Recommendation Output', kind: 'output', description: 'Publishes a policy-compliant recommendation.' },
  { id: 'audit_logger', label: 'Audit Logger', kind: 'process', description: 'Records state and decision events for inspection.' },
]

const positions: Record<string, { x: number; y: number }> = {
  event_trigger: { x: 310, y: 25 }, load_case_state: { x: 310, y: 137 }, evidence_builder: { x: 310, y: 249 }, assess_case: { x: 310, y: 361 }, information_planner: { x: 310, y: 473 },
  contact_policy_gate: { x: 60, y: 585 }, buyer_question_generator: { x: 60, y: 697 }, simulated_buyer_contact: { x: 60, y: 809 }, waiting_for_buyer: { x: 60, y: 921 }, buyer_reply_parser: { x: 310, y: 1033 },
  recovery_proposal: { x: 560, y: 585 }, recovery_policy_gate: { x: 560, y: 697 }, decision_router: { x: 310, y: 1145 }, recommendation_output: { x: 310, y: 1257 }, audit_logger: { x: 310, y: 1369 },
}
const paths: Array<[string, string, string?]> = [
  ['event_trigger', 'load_case_state'], ['load_case_state', 'evidence_builder'], ['evidence_builder', 'assess_case'], ['assess_case', 'information_planner'],
  ['information_planner', 'contact_policy_gate', 'ASK_BUYER'], ['contact_policy_gate', 'buyer_question_generator', 'PERMITTED'], ['buyer_question_generator', 'simulated_buyer_contact'], ['simulated_buyer_contact', 'waiting_for_buyer'],
  ['waiting_for_buyer', 'buyer_reply_parser', 'BUYER_REPLY'], ['buyer_reply_parser', 'evidence_builder', 'REASSESS'], ['information_planner', 'recovery_proposal', 'NO_ASK'], ['recovery_proposal', 'recovery_policy_gate'], ['recovery_policy_gate', 'decision_router'], ['decision_router', 'recommendation_output', 'PERMITTED'], ['decision_router', 'audit_logger', 'BLOCKED / ESCALATE'], ['recommendation_output', 'audit_logger'],
]
const nodeTypes: NodeTypes = { workflow: WorkflowNode }

interface Props { state: ExecutionViewState; onSelectNode: (nodeId: string) => void }

export default function WorkflowCanvas({ state, onSelectNode }: Props) {
  const [instance, setInstance] = useState<ReactFlowInstance<Node<GraphNodeData>, Edge> | null>(null)
  const nodes = useMemo<Node<GraphNodeData>[]>(() => definitions.map((definition) => ({
    id: definition.id, type: 'workflow', position: positions[definition.id], draggable: false, selectable: true,
    data: { ...definition, execution: state.nodes[definition.id], active: state.nodes[definition.id]?.status === 'RUNNING', selected: state.selectedNodeId === definition.id },
  })), [state.nodes, state.selectedNodeId])
  const edges = useMemo<Edge[]>(() => paths.map(([source, target, label], index) => {
    const active = state.nodes[source]?.status === 'RUNNING' || state.nodes[source]?.status === 'COMPLETED' && state.nodes[target]?.status === 'RUNNING'
    const blocked = state.nodes[source]?.status === 'BLOCKED' || state.nodes[source]?.status === 'ESCALATED'
    return { id: `e-${index}`, source, target, label, type: 'smoothstep', animated: Boolean(active), style: { stroke: blocked ? '#d98a7f' : active ? '#78b8aa' : '#343b3e', strokeWidth: active ? 1.8 : 1.2 }, labelStyle: { fill: '#788487', fontSize: 9 }, labelBgStyle: { fill: '#15191b', fillOpacity: 0.96 }, labelBgPadding: [4, 3] }
  }), [state.nodes])
  useEffect(() => {
    if (!instance || !state.autoFollow) return
    const position = positions[state.selectedNodeId]
    if (!position) return
    const zoom = Math.max(instance.getZoom(), 0.58)
    instance.setCenter(position.x + 89, position.y + 52, { zoom, duration: 320 })
  }, [instance, state.selectedNodeId, state.autoFollow])
  return <div className="graph-shell">
    <div className="graph-caption"><span>STATEFUL WORKFLOW</span><span className="graph-line" /><span>{state.runId ?? 'NO ACTIVE RUN'}</span><span className="graph-iteration">ITERATION {state.iteration}</span></div>
    <ReactFlow<Node<GraphNodeData>> nodes={nodes} edges={edges} nodeTypes={nodeTypes} onInit={setInstance} onNodeClick={(_, node) => onSelectNode(node.id)} defaultViewport={{ x: 132, y: 24, zoom: 0.58 }} minZoom={0.25} maxZoom={1.4} nodesDraggable={false} nodesConnectable={false} elementsSelectable>
      <Background color="#3b4446" gap={22} size={1} />
      <Controls showInteractive={false} />
      <MiniMap nodeColor={(node) => ({ event: '#568b86', process: '#48515a', reasoning: '#748cbe', policy: '#b38f5e', waiting: '#bd9960', router: '#688c83', output: '#5b9d83' }[String((node.data as GraphNodeData).kind)] ?? '#48515a')} maskColor="rgba(15,18,20,.78)" />
    </ReactFlow>
  </div>
}
