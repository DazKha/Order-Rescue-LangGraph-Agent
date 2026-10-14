import { Activity, BrainCircuit, CircleDot, Clock3, GitBranch, LockKeyhole, MessageSquareText, Radio, ShieldCheck, Sparkles, Waypoints } from 'lucide-react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { NodeDefinition, NodeExecution } from '../domain/types'

export type GraphNodeData = NodeDefinition & Record<string, unknown> & { execution?: NodeExecution; active?: boolean; selected?: boolean }

const iconFor = { event: Radio, process: Waypoints, reasoning: BrainCircuit, policy: ShieldCheck, waiting: MessageSquareText, router: GitBranch, output: Sparkles }
const kindLabel = { event: 'EVENT', process: 'PROCESS', reasoning: 'LLM REASONING', policy: 'POLICY GATE', waiting: 'EXTERNAL WAIT', router: 'ROUTER', output: 'OUTPUT' }

function WorkflowNode({ data }: NodeProps<Node<GraphNodeData>>) {
  const Icon = iconFor[data.kind]
  const status = data.execution?.status ?? 'PENDING'
  const latest = data.execution?.summary ?? (data.execution?.output ? JSON.stringify(data.execution.output) : '')
  return <div className={`workflow-node kind-${data.kind} status-${status.toLowerCase()} ${data.active ? 'is-active' : ''} ${data.selected ? 'is-selected' : ''}`}>
    <Handle type="target" position={Position.Top} />
    <div className="node-topline"><span className={`node-icon icon-${data.kind}`}><Icon size={14} /></span><span className="node-kind">{kindLabel[data.kind]}</span><span className={`status-dot status-dot-${status.toLowerCase()}`} /></div>
    <div className="node-title">{data.label}</div>
    <div className="node-statusline"><span>{status.replaceAll('_', ' ')}</span>{data.execution?.durationMs ? <span className="node-duration"><Clock3 size={10} /> {data.execution.durationMs}ms</span> : null}</div>
    <div className="node-preview">{latest ? String(latest).replace(/[{}"\[\]]/g, '').slice(0, 75) : status === 'RUNNING' ? <><Activity size={11} className="spin" /> Processing structured events…</> : data.description}</div>
    {data.kind === 'reasoning' && data.execution?.events?.length ? <div className="node-event-count"><CircleDot size={10} /> {data.execution.events.length} trace updates</div> : null}
    {data.kind === 'policy' && data.execution?.events?.length ? <div className="node-event-count"><LockKeyhole size={10} /> Deterministic rules</div> : null}
    <Handle type="source" position={Position.Bottom} />
  </div>
}

export default WorkflowNode
