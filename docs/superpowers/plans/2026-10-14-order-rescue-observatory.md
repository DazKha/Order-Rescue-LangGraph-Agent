# Order Rescue Observatory Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session with review checkpoints. Tasks use checkbox syntax for tracking.

**Goal:** Build a polished React/TypeScript observability prototype for a stateful failed-delivery recovery agent using deterministic, auditable mock events.

**Architecture:** A domain layer owns synthetic cases, evidence and deterministic policy. An event-source layer runs conditional workflows and emits typed structured events. A frontend event store projects those events into per-iteration node traces, case snapshots and timeline entries. React UI components render a React Flow canvas, inspector, buyer interaction, comparison and execution controls.

**Tech Stack:** React, TypeScript, Vite, Tailwind CSS, `@xyflow/react`, Lucide React.

## Global Constraints

- Build an internal developer demo, not the Operations Dashboard.
- Use synthetic data only and do not connect to logistics systems or claim a real dispatch.
- Model one stateful workflow, not multiple agents.
- Render evidence-grounded explainable updates; never show or simulate private chain-of-thought.
- Keep `sources/` read-only.
- Keep mock execution independent of visualization components behind `ExecutionEventSource`.
- Do not add or run a test suite unless the user asks; validate through app build and manual browser interaction.

---

## File Structure

- `package.json`, `index.html`, `vite.config.ts`, `tsconfig*.json`, `postcss.config.js`, `tailwind.config.js`: Vite/TypeScript/Tailwind app setup.
- `src/main.tsx`, `src/App.tsx`, `src/index.css`: React entry, application shell, global styling.
- `src/domain/types.ts`: case state, evidence, event, policy, node and source interfaces.
- `src/domain/cases.ts`: five synthetic case definitions and initial snapshots.
- `src/domain/policy.ts`: deterministic contact and recovery rules with IDs and results.
- `src/engine/MockExecutionEventSource.ts`: conditional workflow event generation, pause-aware event delivery, reply/timeout/disruption inputs, and current case state.
- `src/state/executionReducer.ts`: event projection into execution state, node/iteration history, snapshots, and timeline.
- `src/components/CaseExplorer.tsx`: selectable case list and case status summaries.
- `src/components/ExecutionToolbar.tsx`: run controls, speed, and auto-follow.
- `src/components/WorkflowCanvas.tsx`: read-only React Flow graph and fit/zoom/minimap controls.
- `src/components/WorkflowNode.tsx`: compact typed node rendering with state and summary.
- `src/components/Inspector.tsx`: selected-node tabs, iteration selection, reasoning stream, and structured payloads.
- `src/components/BuyerReplyCard.tsx`: simulated outgoing question and editable reply/timeout controls.
- `src/components/StateDiff.tsx`: snapshot-derived before/after comparison.
- `src/components/ExecutionTimeline.tsx`: chronological clickable event list and event detail.

### Task 1: Bootstrap the application shell

**Files:** Create the Vite configuration and root files listed above, plus `src/main.tsx`, `src/App.tsx`, and `src/index.css`.

- [x] Create a Vite React TypeScript app with the requested libraries and Tailwind configured.
- [x] Build a full-screen dark technical shell with a slim header, synthetic-data indicator, case explorer, graph region, inspector, and bottom timeline placeholders.
- [x] Add responsive sizing rules so controls and panels remain usable at presentation and laptop widths.
- [x] Confirm the production build completes.

### Task 2: Define case, event, and policy domain

**Files:** Create `src/domain/types.ts`, `src/domain/cases.ts`, and `src/domain/policy.ts`.

- [x] Define typed case state, evidence references, node types/status, execution controls, iteration snapshots, timeline events, and reasoning/policy event categories.
- [x] Define `ExecutionEventSource` methods: `startCase(caseId)`, `subscribe(listener)`, `submitBuyerReply(reply)`, `resume()`, `pause()`, `step()`, `setSpeed(speed)`, `reset(caseId)`, and `getCaseState(caseId)`.
- [x] Add five fixtures with distinct starting states and deterministic case outcomes.
- [x] Implement contact and recovery policy evaluators that return rule-by-rule results, policy version, decision, and triggering rule IDs.
- [x] Confirm types represent unknown evidence distinctly and do not equate confidence with permission.

### Task 3: Implement the event-driven mock execution source

**Files:** Create `src/engine/MockExecutionEventSource.ts`.

- [x] Implement a resumable event queue that delivers one structured event at a time and supports configured delays or Instant speed.
- [x] Emit run/case/iteration IDs, timestamp, node ID, duration, input/output, evidence references, and event category/content for every appropriate event.
- [x] Implement conditional initial workflow paths: information request/contact/wait, direct recovery, blocked contact, and escalation.
- [x] Implement CASE-001 buyer reply parsing and second evidence build plus AI assessment; preserve iteration one and emit before/after snapshots.
- [x] Implement CASE-002 timeout without assumed refusal or auto-return, CASE-003 address clarification with autonomous modification blocked, CASE-004 disruption hold and clear event reassessment, and CASE-005 unsupported refusal escalation with automatic return blocked.
- [x] Emit deterministic, auditable policy-rule events and final recommendation/result events; ensure waits stop execution.

### Task 4: Project execution events into frontend state

**Files:** Create `src/state/executionReducer.ts` and update `src/App.tsx`.

- [x] Maintain current case/run, selected node/event, node statuses, active edge, events, node traces grouped by iteration, snapshots, policy output, and waiting/completed state.
- [x] Subscribe to the source and reduce each emitted event before rendering the next event.
- [x] Preserve completed prior-iteration traces and derive state diffs from snapshots.
- [x] Wire Run, Pause, Resume, Step Forward, Reset, speed, auto-follow, case selection, buyer reply, timeout, and disruption-clear actions to source methods.
- [x] Ensure Reset restores initial case state and clears all event and node history.

### Task 5: Build synchronized graph, inspector, and timeline

**Files:** Create `src/components/WorkflowCanvas.tsx`, `WorkflowNode.tsx`, `Inspector.tsx`, and `ExecutionTimeline.tsx`.

- [x] Render a read-only top-to-bottom React Flow graph with event, reasoning, deterministic, policy, waiting, router, and output nodes; show conditional edges, active-edge animation, controls, and minimap.
- [x] Render status, duration, current activity, and final preview on each compact node; select nodes without allowing drag or edit.
- [x] Add Overview/Input/Output/Trace inspector tabs, structured JSON presentation, concise rationale, evidence refs, policy IDs, and iteration selection.
- [x] Expand explainable events progressively by category and distinguish streamed updates from final outputs; do not display raw chain-of-thought.
- [x] Render clickable chronological events and keep timeline selection synchronized with graph and inspector.

### Task 6: Complete case explorer, buyer interaction, and state comparison

**Files:** Create `src/components/CaseExplorer.tsx`, `BuyerReplyCard.tsx`, `StateDiff.tsx`, `ExecutionToolbar.tsx`; integrate in `src/App.tsx` and refine `src/index.css`.

- [x] Show all five cases with ID, scenario, workflow state, delivery status, and last update.
- [x] Show CASE-001's Vietnamese question, editable suggested reply, simulated submit, and waiting affordance; never imply an actual message was sent.
- [x] Show CASE-002 timeout, CASE-004 disruption-clear trigger, and relevant safe alternatives/blocked actions for other cases.
- [x] Present before/after fields from actual snapshots, highlighting only changed values.
- [x] Finish restrained dark visual system, responsive panel behavior, empty/loading/waiting/escalated/blocked states, and accessible control labels.

### Task 7: Integrate and manually verify the demonstration

**Files:** Update the above app files as needed.

- [x] Run the production build and resolve any build/type errors.
- [x] Launch the app and inspect its visible layout and interactions.
- [x] Run CASE-001 through WAITING_FOR_BUYER, submit the suggested reply, and confirm iteration-two evidence build, reassessment, HIGH confidence, permitted retry, state diff, and audit trace.
- [x] Exercise CASE-002 through timeout, CASE-003 through clarification/block, CASE-004 through disruption clearing, and CASE-005 through escalation/block.
- [x] Confirm graph/timeline/inspector synchronization, node iteration history, pause/resume/step/speed/reset, and absence of real logistics actions or private reasoning.
