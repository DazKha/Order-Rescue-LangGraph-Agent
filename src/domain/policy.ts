import type { CaseState, PolicyEvaluation } from './types'

export const evaluateContactPolicy = (state: CaseState): PolicyEvaluation => {
  const rules = [
    { ruleId: 'CON-001', description: 'Clarification is an allowed contact purpose.', evaluatedInput: state.proposedAction, result: 'PASS' as const, detail: 'The question requests evidence needed to resolve delivery.' },
    { ruleId: 'CON-002', description: 'Buyer contact is allowed before return starts.', evaluatedInput: state.returnState, result: state.returnState === 'NOT_STARTED' ? 'PASS' as const : 'FAIL' as const, detail: state.returnState === 'NOT_STARTED' ? 'Return process has not started.' : 'Return process already started; retry contact cannot change the route.' },
    { ruleId: 'CON-003', description: 'Only one clarification request is sent in this demo run.', evaluatedInput: 'contact_count=0', result: 'PASS' as const, detail: 'No clarification has been sent in this run.' },
  ]
  const failed = rules.filter((rule) => rule.result === 'FAIL')
  return { version: 'DEMO-POLICY-1.0', decision: failed.length ? 'BLOCKED' : 'PERMITTED', rules, triggeringRuleIds: failed.map((rule) => rule.ruleId) }
}

export const evaluateRecoveryPolicy = (state: CaseState): PolicyEvaluation => {
  const addressEdit = state.proposedAction === 'MODIFY_SHIPMENT_ADDRESS'
  const autoReturn = state.proposedAction === 'AUTOMATIC_RETURN'
  const retry = state.proposedAction === 'RECOMMEND_STANDARD_RETRY'
  const approvedActions = new Set(['RECOMMEND_STANDARD_RETRY', 'ASK_BUYER_FOR_LANDMARK', 'MODIFY_SHIPMENT_ADDRESS', 'AUTOMATIC_RETURN', 'HOLD_AND_REASSESS', 'WAIT_FOR_BUYER', 'WAIT_FOR_CLARIFICATION', 'ESCALATE_TO_HUMAN'])
  const rules = [
    { ruleId: 'POL-001', description: 'Action exists in approved vocabulary.', evaluatedInput: state.proposedAction, result: approvedActions.has(state.proposedAction) ? 'PASS' as const : 'FAIL' as const, detail: approvedActions.has(state.proposedAction) ? 'The proposal uses a recognized demo action.' : 'This action is not in the approved demo vocabulary.' },
    { ruleId: 'POL-002', description: 'Return process has not started.', evaluatedInput: state.returnState, result: state.returnState === 'NOT_STARTED' ? 'PASS' as const : 'FAIL' as const, detail: state.returnState === 'NOT_STARTED' ? 'Return is not in progress.' : 'A return is already in progress.' },
    { ruleId: 'POL-003', description: 'Attempt limit is not exceeded.', evaluatedInput: `${state.attemptCount}/${state.attemptLimit}`, result: state.attemptCount < state.attemptLimit ? 'PASS' as const : 'FAIL' as const, detail: state.attemptCount < state.attemptLimit ? 'Another recovery step remains within the demo attempt limit.' : 'The configured attempt limit has been reached.' },
    { ruleId: 'POL-004', description: 'Recommendation is inside agent authority.', evaluatedInput: state.proposedAction, result: addressEdit || autoReturn ? 'FAIL' as const : 'PASS' as const, detail: addressEdit ? 'Autonomous shipment-address modification is outside agent authority.' : autoReturn ? 'Automatic return requires verified refusal evidence and human authority.' : 'The agent may recommend this next step but cannot execute logistics actions.' },
    { ruleId: 'POL-005', description: 'Evidence is sufficient for the proposed action.', evaluatedInput: `${state.confidence}; ${state.missingInformation.length} missing`, result: state.missingInformation.includes('refusal_evidence') || state.buyerIntent === 'UNKNOWN' && retry ? 'FAIL' as const : 'PASS' as const, detail: state.missingInformation.includes('refusal_evidence') ? 'Refusal is unsupported by corroborating evidence.' : state.buyerIntent === 'UNKNOWN' && retry ? 'Buyer intent is not confirmed for retry.' : 'Available evidence supports this recommendation.' },
    { ruleId: 'POL-006', description: 'Recovery deadline remains open.', evaluatedInput: 'deadline=within_demo_window', result: 'PASS' as const, detail: 'Synthetic case is inside the configured recovery window.' },
  ]
  const failed = rules.filter((rule) => rule.result === 'FAIL')
  const decision = failed.length ? 'BLOCKED' : 'PERMITTED'
  return { version: 'DEMO-POLICY-1.0', decision, rules, triggeringRuleIds: failed.map((rule) => rule.ruleId) }
}
