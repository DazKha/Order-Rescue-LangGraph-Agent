# BI Schema Alignment Implementation Plan

> **For agentic workers:** Execute this plan in the current project. Each task ends with a focused test cycle.

**Goal:** Align the synthetic LangGraph agent with the workbook's input schema, event contract, decision vocabulary, and illustrative R01–R22 policies while keeping golden outputs out of reasoning inputs.

**Architecture:** Use typed Pydantic models whose input field names mirror the workbook's `Cases` columns. Keep base inputs, later events, and expected outputs in separate JSON artifacts; load later events only after the graph reaches its interrupt, and load expected outputs only in the test harness. An input validation and deterministic policy layer runs before recommendation publication; optional DeepSeek performs assessment only.

**Tech Stack:** Python 3.11+, LangGraph 1.x, Pydantic v2, pytest; no Excel runtime dependency in the agent.

## Global Constraints

- The workbook describes synthetic scenarios and simulated policy, not verified carrier policy.
- Expected labels must never enter the agent state or reasoning prompt.
- Events must remain hidden until the workflow is interrupted and resumed.
- OR-052's synthetic PII example must be redacted before storing derived fixtures or sending model requests.
- No real messaging, dispatch, address updates, COD changes, refunds, or returns may execute.
- Preserve the existing React Observatory and synced `sources/` files.

---

### Task 1: Build separated BI fixtures and schema tests

**Files:**
- Create: `data/fixtures/bi_inputs.json`
- Create: `data/fixtures/bi_events.json`
- Create: `data/expected/bi_expected.json`
- Create: `tests/test_bi_contract.py`
- Modify: `data/source/README.md`

**Interfaces:**
- Inputs contain only the 27 observable `Cases` fields.
- Events contain only case ID and event fields, loaded after interrupt.
- Expected outputs contain workbook labels and are imported only by tests.

- [x] Test that 56 cases are split into independent inputs/events/expected records, no expected field appears in agent input, events load separately, and OR-052's note is redacted.
- [x] Run the contract test and verify the failure points to the missing separation/fixtures behavior.
- [x] Generate sanitized JSON from the supplied workbook, preserve all case IDs and all non-sensitive inputs/labels, and redact OR-052's note.
- [x] Run the contract test and verify all 56 fixture records pass.

### Task 2: Add workbook-compatible domain schemas and fail-closed validation

**Files:**
- Modify: `agent/schemas.py`
- Create: `agent/bi_adapter.py`
- Test: `tests/test_bi_contract.py`

**Interfaces:**
- `BiCaseInput` represents workbook input columns with exact names and nested attempt/contact/disruption objects.
- `CaseEvent` represents delayed BUYER/SELLER/TIMEOUT/DISRUPTION events.
- `validate_case_input(raw: dict) -> InputValidationResult` reports required-field and enum failures without passing expected labels to the graph.
- Enums match workbook vocabulary for raw status, hypothesis, buyer intent, eligibility, action, and policy gate.

- [x] Add failing tests for all workbook enum values, `CONDITIONAL`, unknown return/deadline handling, missing required fields, and invalid status.
- [x] Run focused tests and verify expected failures.
- [x] Implement schemas and deterministic input validation.
- [x] Run focused tests and verify all pass.

### Task 3: Make LangGraph consume BI input and resume with delayed events

**Files:**
- Modify: `agent/state.py`
- Modify: `agent/graph.py`
- Modify: `agent/nodes.py`
- Modify: `agent/fixtures.py`
- Modify: `demo.py`
- Test: `tests/test_flow.py`

**Interfaces:**
- `load_bi_case(case_id)` returns only observable input state.
- `load_bi_event(case_id)` is invoked only after graph interrupt in tests/demo.
- Graph assessment accepts a structured case context plus current evidence; expected outputs are not accepted by any node.
- Every decision-relevant event resumes through evidence build and reassessment.

- [x] Add failing tests for OR-001 values, separate delayed events, seller replies, no-reply/timeout uncertainty, and two-pass assessment.
- [x] Run focused tests to verify the current graph fails the BI contract.
- [x] Refactor state and nodes to use workbook input names and Pydantic event types.
- [x] Run focused tests and verify pass.

### Task 4: Implement deterministic BI policy gates and safe recovery proposals

**Files:**
- Modify: `agent/policy.py`
- Modify: `agent/nodes.py`
- Test: `tests/test_policy.py`
- Test: `tests/test_bi_cases.py`

**Interfaces:**
- `evaluate_contact_policy(case, questions_asked)` returns a workbook-compatible policy decision plus R12/R22 results.
- `evaluate_recovery_policy(action, case, assessment)` returns eligibility, `PERMITTED|BLOCKED|ESCALATED`, and triggering R01–R22 IDs.
- Deterministic gates cover deadline, attempts, return lifecycle, address/COD/damage conflicts, disruption verification, actor authority, PII, input validity, prompt-injection data, and stale/duplicate events.
- Expected labels are used only by parametrized tests to compare graph output.

- [x] Add focused failing tests for every policy family and representative workbook cases.
- [x] Run focused tests and inspect failures.
- [x] Implement narrow deterministic rules with rule IDs and fail-closed defaults.
- [x] Run focused tests, then the full 56-case comparison; no hypothesis, missing-information, action, eligibility, or policy-gate mismatches remain in the tested fields.

### Task 5: Revalidate optional LLM boundary and documentation

**Files:**
- Modify: `agent/reasoning.py`
- Modify: `tests/test_reasoning.py`
- Modify: `README.md`
- Modify: `data/source/README.md`

- [x] Test that LLM input contains only current observable fields/evidence, never expected labels or unrevealed events.
- [x] Run full pytest, compile check, and OR-001 deterministic demo.
- [x] Document actual workbook coverage, policy status, supported CLI, mock boundaries, and known limits.
- [ ] Live DeepSeek smoke not run: `DEEPSEEK_API_KEY` is not present in the process environment. The structured request/response path is covered with a mocked transport; use a rotated key through the environment to verify the live provider.
