import { ArrowRightLeft, Minus } from 'lucide-react'
import type { CaseState } from '../domain/types'

const fields: Array<{ key: keyof CaseState; label: string; format?: (value: unknown) => string }> = [
  { key: 'buyerIntent', label: 'Buyer intent' }, { key: 'confidence', label: 'Confidence' }, { key: 'proposedAction', label: 'Recommendation' },
  { key: 'hypothesis', label: 'Hypothesis', format: (value) => String(value).replaceAll('_', ' ').toLowerCase() },
]
interface Props { before?: CaseState; after?: CaseState }
export default function StateDiff({ before, after }: Props) {
  if (!before || !after || before === after) return <div className="diff-empty"><Minus size={13} /> State changes appear after new evidence arrives.</div>
  const changed = fields.filter(({ key }) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
  return <div className="state-diff">
    <div className="diff-heading"><span><ArrowRightLeft size={12} /> STATE CHANGES</span><span>{changed.length} fields</span></div>
    {changed.length ? changed.map(({ key, label, format }) => {
      const left = format ? format(before[key]) : String(before[key] ?? '—').replaceAll('_', ' ')
      const right = format ? format(after[key]) : String(after[key] ?? '—').replaceAll('_', ' ')
      return <div className="diff-row" key={key}><span className="diff-field">{label}</span><span className="diff-values"><span className="diff-before">{left}</span><span className="diff-arrow">→</span><span className="diff-after">{right}</span></span></div>
    }) : <div className="diff-empty"><Minus size={13} /> No tracked fields changed.</div>}
  </div>
}
