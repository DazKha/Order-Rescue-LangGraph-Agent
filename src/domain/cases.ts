import type { CaseId, CaseState } from './types'

const t = '2026-10-14T10:00:00.000Z'

export const cases: CaseState[] = [
  {
    caseId: 'CASE-001', scenario: 'Buyer at Work', deliveryStatus: 'RECIPIENT_UNAVAILABLE', courierNote: 'Called recipient but no answer.', attemptCount: 1, attemptLimit: 3,
    returnState: 'NOT_STARTED', buyerIntent: 'UNKNOWN', hypothesis: 'TEMPORARY_UNAVAILABILITY', confidence: 'LOW', missingInformation: ['buyer_intent'],
    proposedAction: 'ASK_BUYER', evidence: [
      { id: 'EVID-001', label: 'Delivery status', detail: 'Recipient unavailable', source: 'Courier event', timestamp: t },
      { id: 'EVID-002', label: 'Courier note', detail: 'Called recipient but no answer.', source: 'Courier note', timestamp: t },
    ], workflowStatus: 'IDLE', lastUpdated: 'Just now',
  },
  {
    caseId: 'CASE-002', scenario: 'No Reply', deliveryStatus: 'RECIPIENT_UNAVAILABLE', courierNote: 'No answer on first attempt.', attemptCount: 1, attemptLimit: 2,
    returnState: 'NOT_STARTED', buyerIntent: 'UNKNOWN', hypothesis: 'TEMPORARY_UNAVAILABILITY', confidence: 'LOW', missingInformation: ['buyer_intent'],
    proposedAction: 'ASK_BUYER', evidence: [{ id: 'EVID-021', label: 'Delivery attempt', detail: 'No answer on first attempt.', source: 'Courier note', timestamp: t }], workflowStatus: 'IDLE', lastUpdated: '12 min ago',
  },
  {
    caseId: 'CASE-003', scenario: 'Unclear Address', deliveryStatus: 'ADDRESS_INCOMPLETE', courierNote: 'Address is missing a recognizable landmark.', attemptCount: 1, attemptLimit: 3,
    returnState: 'NOT_STARTED', buyerIntent: 'UNKNOWN', hypothesis: 'INSUFFICIENT_ADDRESS_DETAIL', confidence: 'HIGH', missingInformation: ['address_landmark'],
    proposedAction: 'ASK_BUYER_FOR_LANDMARK', evidence: [{ id: 'EVID-031', label: 'Courier note', detail: 'Address is missing a recognizable landmark.', source: 'Courier note', timestamp: t }], workflowStatus: 'IDLE', lastUpdated: '36 min ago',
  },
  {
    caseId: 'CASE-004', scenario: 'Service Disruption', deliveryStatus: 'DELIVERY_DELAYED', courierNote: 'Route affected by temporary depot disruption.', attemptCount: 0, attemptLimit: 3,
    returnState: 'NOT_STARTED', buyerIntent: 'UNKNOWN', disruptionActive: true, hypothesis: 'SERVICE_DISRUPTION', confidence: 'HIGH', missingInformation: [],
    proposedAction: 'HOLD_AND_REASSESS', evidence: [{ id: 'EVID-041', label: 'Operations signal', detail: 'Temporary depot disruption is active.', source: 'Synthetic operations event', timestamp: t }], workflowStatus: 'IDLE', lastUpdated: '1 hr ago',
  },
  {
    caseId: 'CASE-005', scenario: 'Refused Without Evidence', deliveryStatus: 'REFUSED', courierNote: 'Refused status has no supporting detail.', attemptCount: 1, attemptLimit: 3,
    returnState: 'NOT_STARTED', buyerIntent: 'UNKNOWN', hypothesis: 'UNVERIFIED_REFUSAL', confidence: 'LOW', missingInformation: ['refusal_evidence'],
    proposedAction: 'AUTOMATIC_RETURN', evidence: [{ id: 'EVID-051', label: 'Delivery status', detail: 'REFUSED; no signature or corroborating note.', source: 'Courier event', timestamp: t }], workflowStatus: 'IDLE', lastUpdated: '2 hr ago',
  },
]

export const getInitialCase = (caseId: CaseId): CaseState => structuredClone(cases.find((item) => item.caseId === caseId)!)
