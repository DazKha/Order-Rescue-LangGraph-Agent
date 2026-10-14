# Order Rescue Agent Execution Observatory — Design Spec

## Goal

Build a polished, full-screen developer observability prototype that demonstrates how a stateful Order Rescue agent reasons from synthetic delivery evidence, waits for buyer information, reassesses new evidence, applies deterministic policy, and produces an auditable recommendation.

## Scope and constraints

- Build an internal technical demo, not the Operations Dashboard.
- Use React, TypeScript, Vite, Tailwind CSS, `@xyflow/react`, and Lucide React.
- Use synthetic data and a deterministic mock event source; do not connect to logistics systems or claim a courier was dispatched.
- Treat each case as a single stateful workflow, not a multi-agent system.
- Display concise, evidence-grounded explainable updates only. Never expose or simulate private chain-of-thought.
- Keep `sources/` read-only and do not edit, move, rename, or delete synced files.

## Experience

The dark, restrained developer-tool UI has four working regions: a left case explorer for five synthetic scenarios; a central, read-only React Flow graph with conditional paths and status-bearing nodes; a right inspector with Overview, Input, Output, and Trace tabs; and a bottom execution timeline. The graph uses distinct event, reasoning, deterministic, policy, waiting, and final node treatments. Node selection and timeline selection stay synchronized. Fit, zoom, and minimap controls support presentation. Reasoning expands in the inspector so graph nodes remain compact and do not overlap.

A compact toolbar provides Run, Pause, Resume, Step Forward, Reset, and 0.5x/1x/2x/Instant speed. Auto-follow can be toggled. Execution stops at external waits and does not loop indefinitely. Every interaction is labeled as simulated.

## Workflow and case behavior

The event source emits typed, incremental events. A delivery-failure run loads case state, builds evidence, assesses the case, evaluates whether buyer information could change the next action, and then routes conditionally through contact policy, question generation, simulated contact, and `WAITING_FOR_BUYER`, or directly to recovery proposal and policy. A submitted buyer reply emits a `BUYER_REPLY`, parses structured evidence, updates the evidence pack, then runs Evidence Builder and AI Assessment again before planning, proposing recovery, checking policy, routing, publishing a recommendation, and auditing.

For CASE-001, the initial hypothesis is temporary unavailability with LOW confidence and unknown buyer intent. The simulator asks “Bạn vẫn muốn nhận đơn hàng này chứ?” and waits. The editable suggested reply says “Hôm qua mình đi làm nên không nghe máy. Mình vẫn muốn nhận hàng.” Submitting it results in `WANTS_DELIVERY`, HIGH confidence, `RECOMMEND_STANDARD_RETRY`, and a deterministic `PERMITTED` policy decision. The recommendation means an eligible next step only; it never represents a real dispatch.

CASE-002 does not infer refusal from silence; it emits a timeout and recommends WAIT or ESCALATE under demo policy, never automatic return. CASE-003 permits clarification but blocks autonomous address modification and routes to clarification or approved human handling. CASE-004 attributes the failure to a synthetic service disruption, recommends HOLD_AND_REASSESS, and can reassess when the disruption clears. CASE-005 treats an unsupported REFUSED status as insufficient evidence, blocks automatic return, and escalates to a human.

## Event and state model

`ExecutionEventSource` defines start execution, subscribe to events, submit buyer reply, resume execution, and retrieve current case state. `MockExecutionEventSource` implements this interface. Events carry event/run/case IDs, iteration, node ID, event type, timestamp, and structured input/output or category/content/evidence references as appropriate. Supported event families include node lifecycle/progress, evidence observation, hypothesis/confidence/missing-information updates, information request, decision proposal, policy check start/rule/decision, state transition, completion, and failure.

The frontend event store is the source of display state: it incrementally updates active/completed/waiting/blocked/escalated nodes, inspector details, per-node traces, global timeline, and snapshots. Iterations are retained rather than overwritten. State comparison is computed from actual before/after snapshots. Pause/resume controls event presentation without corrupting the case state. Reset restores initial state, statuses, and history.

## Reasoning and policy display

Reasoning events use restrained categories: Observation, Hypothesis, Uncertainty, Confidence, Decision, Policy, and Result. LLM-powered nodes show progressive observable summaries and final validated structured output. The Information-Seeking Planner evaluates decision impact and eligibility, not merely whether a missing-information list is non-empty. Policy gates show policy version, each rule ID, evaluated input, PASS/FAIL, final decision, and the exact blocking rule where applicable. AI confidence, evidence sufficiency, and policy eligibility remain distinct; high confidence cannot bypass policy.

The inspector exposes input, structured output, evidence references, duration, concise rationale, rule IDs, and iteration-specific trace. Audit events include timestamp, iteration, node, evidence references, previous and updated state, policy decision, rule ID, and recommendation. Timeline events navigate to their graph node and reveal event details.

## Architecture boundaries

- **Domain and mock cases:** synthetic case fixtures, evidence/state types, policy rules, and deterministic case decisions.
- **Execution source:** event-driven mock workflow and `ExecutionEventSource` adapter boundary; no UI dependencies.
- **Event store:** consumes source events and derives node states, histories, snapshots, and timeline.
- **Visualization:** graph node/edge definitions and read-only React Flow canvas.
- **Application UI:** case explorer, controls, inspector, buyer interaction, state diff, and timeline.

The source interface is designed so a future FastAPI SSE/LangGraph adapter can replace the mock source. The UI consumes structured observability events and does not require token-level model output.

## Failure handling

An execution failure becomes a visible `NODE_FAILED` event with node context and an auditable timeline entry. A failed source operation leaves the last consistent case snapshot inspectable and allows reset. Unknown or missing evidence is represented as unknown; it is not converted into buyer refusal or permission. Policy blocks and escalation are terminal outcomes for the relevant run unless a new external event is submitted.

## Verification approach

Review the production build and exercise the demo flow in the browser: start CASE-001, observe progressive events and the waiting state, submit an edited or suggested reply, confirm iteration-two reassessment and the state diff, then inspect policy and audit details. Exercise each other case's conditional route and confirm reset, pause/resume, step, speed, and auto-follow behavior. No live logistics integration is part of verification.

## Acceptance criteria

The prototype satisfies both supplied prompts when the five cases work; the graph, inspector, and timeline stay synchronized; structured events progressively drive observable traces; buyer reply triggers a second evidence build and assessment; earlier iterations remain inspectable; state diff comes from stored snapshots; policy rules are deterministic and visibly separate from AI confidence; external waits stop execution; blocked actions and escalation are explicit; and no private chain-of-thought or real-world logistics action is shown.
