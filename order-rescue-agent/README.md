# Order Rescue Agent V0

A minimal LangGraph workflow for synthetic failed-delivery cases. By default, assessment uses deterministic mock reasoning. An optional DeepSeek provider can perform the structured assessments; information planning, candidate actions, and the safety policy remain deterministic. The agent asks one buyer clarification when it can change the recovery action, pauses with a LangGraph interrupt, reassesses after a simulated reply, and applies illustrative policy before publishing a recommendation.

## Requirements and setup

- Python 3.11 or newer
- LangGraph 1.x, Pydantic 2.x, and pytest 8.x

From this directory:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the interactive demo:

```sh
python demo.py
```

Run with the synthetic buyer reply fixture:

```sh
python demo.py --auto
```

To use DeepSeek for both assessments, provide the key through the process environment and opt in:

```sh
export DEEPSEEK_API_KEY="your-key"
python demo.py --auto --llm
```

The default model is `deepseek-flash`; set `DEEPSEEK_MODEL` to change it. The agent sends only the current case context and evidence to the provider. Do not put API keys in source files or fixtures.

Or provide a simulated response directly:

```sh
python demo.py --reply "I still want delivery."
```

Run the test suite:

```sh
python -m pytest -q
```

The CLI options are `--auto`, `--reply TEXT`, and `--llm`.

## Architecture

- `agent/schemas.py` defines the Pydantic domain models and explicit enums.
- `agent/state.py` defines the LangGraph `TypedDict` shared state and deduplicating evidence/event reducers.
- `agent/reasoning.py` contains the replaceable `Reasoner` interface and deterministic V0 implementation.
- `agent/reasoning.py` also contains the opt-in DeepSeek structured-output client; provider output is validated against the Pydantic assessment schema and evidence references. When confirmed buyer intent resolves the only missing item for a temporary availability conflict, an evidence-based guard clears that stale gap and sets confidence to HIGH.
- `agent/nodes.py` implements the evidence, assessment, information planning, contact gate, question, interrupt, parsing, proposal, recovery gate, and finalization nodes.
- `agent/policy.py` contains pure, rule-ID-based illustrative policy functions.
- `agent/graph.py` compiles the single stateful workflow with an in-memory checkpointer keyed by stable case ID.
- `agent/events.py` creates structured, explainable execution events for later observability streaming.
- `data/fixtures/or_001.json` holds only observable inputs. The reply fixture is isolated in `or_001_reply.json` and is read only after the graph reaches its interrupt.

## Implemented

- OR-001 starts with a `DELIVERY_FAILED` event and `RECIPIENT_UNAVAILABLE` status, assesses `TEMP_AVAILABILITY_CONFLICT` at MEDIUM confidence, identifies missing `buyer_intent`, requests clarification, and enters `WAITING_FOR_BUYER`.
- A confirming simulated reply is preserved as evidence, parsed into buyer intent, and triggers a second evidence build and assessment before proposing `STANDARD_REATTEMPT`.
- A recovery policy gate checks action vocabulary, return lifecycle, retry limit, and unsupported-refusal handling before `finalize` can publish a recommendation.
- Ambiguous replies remain unknown and route to human review after the one-question limit.
- Clear negative intent, including “I don't want delivery” and “I no longer want delivery,” produces `NO_ACTION`; ambiguous or contradictory replies stay unknown for review.
- DeepSeek output with unregistered `missing_information` values is rejected by schema validation rather than entering workflow routing.
- Execution events include lifecycle, assessment, clarification, buyer reply, policy, state transition, and recommendation events.
- The final recommendation is decision support only; it reports `executed=False` and has no side effects.

## Mocked and not implemented

- The BI workbook `data/source/order_rescue_simulation_cases_v0.1.xlsx` was unavailable. `data/source/README.md` records this, and the OR-001 fixture is a fallback based on the user-supplied prompt, not BI-prepared data.
- The default reasoning, reply classification, delivery context, buyer interaction, and demo policy are deterministic and synthetic. The optional DeepSeek path makes external model calls for assessment only; it does not control policy or actions. Demo rules are not verified Shopee/SPX rules.
- There is no durable database, real messaging, logistics integration, courier dispatch, address modification, refund, or return execution.
- The in-memory checkpointer preserves state only for the lifetime of the running process; it does not survive restarts.

## Validation performed

- `.venv/bin/python -m pytest -q tests` — 22 tests passed.
- `.venv/bin/python -m compileall -q agent demo.py` — passed.
- `.venv/bin/python demo.py --auto` — completed the full synthetic interrupt/resume flow and returned a permitted `STANDARD_REATTEMPT` recommendation with `Executed: no`.
- `DEEPSEEK_API_KEY=<provided key> .venv/bin/python demo.py --auto --llm` — live provider smoke completed both assessments; the resumed assessment reached HIGH confidence, deterministic policy returned PERMITTED, and the recommendation remained unexecuted.

The API key was supplied through the process environment for the live smoke and was not written into project files.

## Next steps

When the BI workbook becomes available, inspect the listed sheets, reconcile vocabulary and policy differences explicitly, and update the fixtures/tests without passing expected labels into the reasoning node. A production-facing iteration would need an approved durable checkpoint store, authenticated service boundary, real policy ownership, and a separately reviewed integration plan.
