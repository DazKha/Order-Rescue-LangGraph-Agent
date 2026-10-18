# Naive LLM-assisted Order Rescue Flow

## Goal

Build a small end-to-end prototype that gives the LLM a meaningful role in interpreting a case, choosing the next allowed branch, understanding a buyer or operational reply, and proposing a recovery action. Keep deterministic policy as the final authority. The prototype should be easy to inspect and extend into independently prompted nodes after its behavior is understood.

## Scope

- Change the Python LangGraph agent under `order-rescue-agent/` only.
- Keep the React Observatory and its mock event source separate and unchanged.
- Keep input validation, evidence construction, contact-policy enforcement, interrupts/checkpointing, recovery-policy enforcement, and final status construction deterministic.
- Do not add external tools or real-world side effects. Recommendations remain unexecuted.
- Use DeepSeek only when explicitly enabled with `--llm`; retain deterministic mock reasoning otherwise.

## Proposed flow

1. Validate the case and build its evidence pack with existing deterministic nodes.
2. Make one structured LLM call for the current decision point. On the initial pass, return:
   - the assessment (hypothesis, confidence, missing information, evidence references, concise summary);
   - a route selected from a fixed allowlist (`ASK`, `WAIT_FOR_EVENT`, or `PROPOSE_RECOVERY`), with the target when waiting;
   - a draft question when the route requires one, or a candidate action when the route proposes recovery.
3. Map the LLM route to existing LangGraph branches. A request to contact a person or wait for an operational event must pass the deterministic contact-policy gate before the workflow asks or waits.
4. After a simulated buyer, seller, or operations event resumes the workflow and evidence is rebuilt, make one structured LLM call with the updated evidence and raw event. Return parsed event facts/intent, an updated assessment, and a candidate recovery action with its short rationale and evidence references.
5. Evaluate the candidate action with the existing deterministic recovery-policy gate. Finalize action, policy decision, status, and `executed=false` from validated state; do not let the LLM change those fields.

The prompt and output are intentionally grouped by decision point for this first version. The implementation may adapt the existing nodes to pass these structured results through state without introducing a general-purpose autonomous supervisor.

## LLM output constraints

- Use typed structured output and registered enums for routes, hypotheses, intents, and actions.
- Validate evidence references against the evidence available in the current iteration.
- Preserve the raw reply as evidence; represent ambiguous intent as `UNKNOWN` rather than guessing.
- The LLM may select only an allowed route. LangGraph retains fixed routing, and deterministic gates decide whether the selected route can proceed.
- A model timeout, invalid JSON, invalid enum, or unsupported evidence reference must stop the decision safely with a visible error/escalation outcome. Do not silently switch from DeepSeek to the mock reasoner when `--llm` was requested.

## Deliberately deferred

- LLM-generated policy decisions or per-rule PASS/BLOCK results. The deterministic policy implementation remains authoritative.
- LLM-authored final status or execution fields. The final node assembles these deterministically.
- Splitting each semantic task into a separate prompt/node, production API service, React integration, real buyer contact, carrier integration, or logistics execution.
- A general supervisor that may choose arbitrary nodes or repeat steps without a bounded route.

## Acceptance criteria

- With `--llm`, the model can select an allowed route from the assessment and evidence, and its question or candidate action is carried through the existing LangGraph flow.
- After a simulated reply/event, the model can extract structured information, reassess with updated evidence, and propose a candidate action.
- Contact and recovery policy decisions remain deterministic and cannot be bypassed by an LLM response.
- Malformed or unsupported model output cannot produce a permitted recommendation.
- Without `--llm`, the current deterministic mock path remains available.
- Final output clearly remains a recommendation with no real-world action executed.
