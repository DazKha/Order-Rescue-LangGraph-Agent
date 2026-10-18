# Order Rescue LangGraph Agent

A minimal, stateful LangGraph workflow for the synthetic failed-delivery cases in the BI workbook. It validates case input, assesses evidence, asks a buyer or authorized actor for clarification when useful, pauses at an interrupt, reassesses after a later event, and gates recommendations through deterministic policy checks. It never sends real messages, dispatches a courier, changes an address/payment method, issues refunds, or starts returns.

## BI schema coverage

The agent was aligned against all 56 workbook cases and the `Cases`, `Policy_Rules`, `Field_Dictionary`, and related sheets. Typed input fields mirror the case input columns; the enums preserve BI's hypothesis, action, buyer intent, return state, eligibility, and policy decision vocabularies.

The test data is separated by role:

- `data/fixtures/bi_inputs.json` contains observable inputs only.
- `data/fixtures/bi_events.json` stores delayed buyer, seller, timeout, and operational events; loaders expose these only after an interrupt.
- `data/expected/bi_expected.json` contains proposed BI labels for tests. It is not imported into the graph or sent to DeepSeek.

The source workbook is not copied into this repository. OR-052's synthetic PII marker is redacted in the derived input fixture. BI labels and the simulated R01-R22 policies are treated as evaluation guidance, not verified carrier policy. See `data/source/README.md` for provenance details.

## Setup

Requires Python 3.11+, LangGraph 1.x, Pydantic 2.x, and pytest 8.x.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run a case

Run the OR-001 interrupt/resume flow using its synthetic BI event:

```sh
python demo.py --auto
```

Select another case with `--case`, for example:

```sh
python demo.py --case OR-038 --auto
```

If the case reaches another interrupt after the fixture event, the CLI leaves the checkpoint waiting and shows the next requested information. Provide a simulated reply interactively or pass one with `--reply TEXT`.

To use DeepSeek for structured assessments, provide `DEEPSEEK_API_KEY` through the process environment and opt in:

```sh
export DEEPSEEK_API_KEY="your-key"
python demo.py --auto --llm
```

Set `DEEPSEEK_MODEL` to override the default model. The provider only performs evidence assessment. Information planning, action choice, and policy gates remain deterministic. The API key must not be stored in source files or fixtures.

## Architecture

- `agent/schemas.py` defines typed BI input/event models and domain enums.
- `agent/bi_adapter.py` validates required fields, timestamps, and registered input enums.
- `agent/state.py` defines the shared LangGraph state and evidence/event reducers.
- `agent/fixtures.py` loads case inputs and later events separately.
- `agent/reasoning.py` provides deterministic assessment and an optional DeepSeek JSON client with Pydantic and evidence-reference validation.
- `agent/nodes.py` implements validation, evidence construction, assessment, information planning, interrupt/resume, reassessment, recommendation, policy gate, and finalization.
- `agent/policy.py` implements deterministic illustrative policy rules with rule IDs.
- `agent/graph.py` compiles the checkpointed workflow. The default in-memory checkpoint lasts only for the current process.

## Verification

Run the test suite and syntax check:

```sh
python -m pytest -q
python -m py_compile agent/*.py demo.py
```

The tests compare initial and resumed assessment/action/policy fields against the separate expected labels for all 56 BI cases. They also verify schema separation, hidden-event handling, invalid-input gates, evidence isolation, and the optional LLM request boundary. Use `python demo.py --auto` to inspect the OR-001 flow.

## Limits

This is synthetic decision support. BI's illustrative policies and labels are not authorized operational rules. The default checkpointer is in memory, and there is no production service boundary, durable state store, real buyer messaging, carrier integration, or logistics side effect.
