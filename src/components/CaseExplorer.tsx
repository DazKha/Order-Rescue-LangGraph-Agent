import { Activity, AlertTriangle, Check, Circle, Clock3, MapPinned, PackageCheck, UserRound, Waves } from 'lucide-react'
import { cases } from '../domain/cases'
import type { CaseId, ExecutionViewState } from '../domain/types'

const icons = [UserRound, Clock3, MapPinned, Waves, AlertTriangle]
interface Props { selectedCase: CaseId; state: ExecutionViewState; onSelect: (id: CaseId) => void }

export default function CaseExplorer({ selectedCase, state, onSelect }: Props) {
  return <aside className="case-explorer">
    <div className="section-heading"><span>CASE EXPLORER</span><span className="count-badge">05</span></div>
    <div className="case-list">{cases.map((item, index) => {
      const Icon = icons[index]
      const active = item.caseId === selectedCase
      const status = active ? state.status : item.workflowStatus
      return <button className={`case-card ${active ? 'selected' : ''}`} key={item.caseId} onClick={() => onSelect(item.caseId)}>
        <span className="case-icon"><Icon size={15} /></span>
        <span className="case-content"><span className="case-title-row"><strong>{item.scenario}</strong>{active ? <span className="case-live-dot" /> : null}</span>
          <span className="case-id">{item.caseId}</span>
          <span className="case-meta"><span className={`case-status status-${status.toLowerCase()}`}><i />{status.replaceAll('_', ' ')}</span></span>
          <span className="case-delivery"><PackageCheck size={11} /> {item.deliveryStatus.replaceAll('_', ' ')}</span>
          <span className="case-updated">{active && state.events.length ? 'Updated just now' : item.lastUpdated}</span>
        </span>
      </button>
    })}</div>
    <div className="sidebar-footer"><div className="footer-icon"><Activity size={14} /></div><div><strong>Mock environment</strong><span>Synthetic case data</span></div><Check size={13} className="footer-check" /></div>
    <div className="privacy-note"><Circle size={8} fill="currentColor" /> No external systems connected</div>
  </aside>
}
