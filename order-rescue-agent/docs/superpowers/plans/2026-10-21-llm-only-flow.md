# LLM-only Order Rescue Flow Implementation Plan

> **For agentic workers:** Execute the tasks in order with focused verification after each behavior change.

**Goal:** Make the Python agent follow validate → evidence → LLM assessment → buyer question/wait or recovery proposal → deterministic policy → final/ops, with resumed events returning to validation.

**Architecture:** Keep the fixed LangGraph topology and deterministic eligibility/policy gates. Use DeepSeek for assessment on every eligible pass, including after a simulated event. Keep prompts in `agent/prompts.py` and allow injected decision providers only for tests.

**Tech Stack:** Python 3.11+, LangGraph, Pydantic, DeepSeek chat completions, pytest.

## Global Constraints

- All cases and replies remain synthetic; no real messaging, carrier API, dispatch, address/payment change, refund, or return.
- The root React Observatory and `sources/` are untouched.
- Expected labels stay out of agent input and prompts.
- Deterministic policy remains authoritative; LLM output is a candidate.
- The BI v0.5 workbook is present, while current runtime fixtures still reflect v0.1 until schema migration is completed.

---

### Task 1: Define the LLM-only graph contract

**Files:** `tests/test_flow.py`, `agent/graph.py`, `agent/nodes.py`, `agent/state.py`.

- [x] Write a graph integration test using an injected decision provider: initial run interrupts, resume visits `validate_input` before `build_evidence`, then reassesses once using the event.
- [x] Run the focused test and confirm the current resume path fails.
- [x] Route resume to validation, let `assess_case` handle the after-event decision, and remove the separate parse node and its state fallback.
- [x] Run the focused test and confirm it passes.

### Task 2: Remove runtime mock reasoning

**Files:** `agent/reasoning.py`, `agent/graph.py`, `demo.py`, `ui/index.html`, `tests/test_flow.py`, `tests/test_bi_cases.py`, `tests/test_bi_contract.py`, `tests/test_demo.py`.

- [x] Add a focused test that an eligible case without a configured LLM raises a clear key error, while a preflight rejection requires no LLM.
- [x] Run it and confirm the old mock default fails the expectation.
- [x] Remove `DeterministicMockReasoner` and runtime mock mode; use DeepSeek unless a decision provider is injected for tests.
- [x] Replace old mock-dependent graph tests with LLM-boundary integration tests; keep pure policy and fixture contract checks.
- [x] Run affected tests.

### Task 3: Centralize model prompts and align the user flow

**Files:** `agent/prompts.py`, `agent/reasoning.py`, `agent/nodes.py`, `ui/index.html`, `README.md`, `tests/test_reasoning.py`.

- [x] Add a request-payload test covering initial and after-event prompts, evidence references, and buyer-only simulated question constraints.
- [x] Run it and confirm failure before moving prompt text.
- [x] Move all LLM prompt content and schema instructions into `agent/prompts.py`; keep transport and validation in `agent/reasoning.py`.
- [x] Remove the UI mode toggle and CLI `--llm`; document DeepSeek as required for eligible cases and update the flow diagram.
- [x] Run focused tests and compile checks for the changed Python files.

### Task 4: Verify policy and state boundaries

**Files:** `tests/test_flow.py`, `tests/test_reasoning.py`, `README.md`.

- [x] Verify that a resumed event fails precheck before another LLM call when lifecycle becomes ineligible.
- [x] Verify that a permitted recommendation is published only after the deterministic gate and has `executed=False`.
- [x] Run the relevant suite and report any legacy test assumptions that still require the separate v0.5 schema migration.
