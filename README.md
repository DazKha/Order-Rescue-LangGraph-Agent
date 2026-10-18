# Order Rescue · Agent Observatory

A synthetic developer observability prototype for a stateful delivery-recovery workflow. It visualizes evidence, explainable decision updates, deterministic policy checks, buyer waits, reassessment, and audit events. No logistics service is connected and recommendations do not dispatch a courier.

## Run locally

```sh
npm install
npm run dev
```

Vite prints the local URL when the development server starts. Use **Run case** to stream the selected scenario. CASE-001 pauses for a simulated buyer reply; submitting the reply starts a second evidence build and assessment. Select **Instant** to skip event delays, or use Pause, Resume, and Step Forward to inspect the stream.

## Architecture

- `src/domain/` contains the typed case state, synthetic fixtures, and deterministic policy rules.
- `src/engine/MockExecutionEventSource.ts` emits structured mock execution events through the `ExecutionEventSource` interface.
- `src/state/` projects the event stream into node traces, iterations, state snapshots, and timeline items.
- `src/components/` renders the React Flow graph and synchronized case, inspector, and timeline views.

All displayed case data and communication are simulated. Explainable event summaries are shown; private chain-of-thought is not.

## Python LangGraph agent V0

The repository also contains a separate, minimal Python implementation of the synthetic Order Rescue workflow. It uses LangGraph checkpointing and `interrupt()` / `Command(resume=...)` for the simulated buyer pause, performs reassessment and deterministic policy checks, and never executes logistics actions.

See [`order-rescue-agent/README.md`](order-rescue-agent/README.md) for setup, `python demo.py --auto`, the 56-case BI schema/event alignment, tests, and mock boundaries. The Python agent remains separate from the React Observatory.
