# Naive LLM-assisted Order Rescue Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small LLM-assisted end-to-end decision flow to the Python Order Rescue agent while keeping policy, validation, and execution status deterministic.

**Architecture:** Keep the existing LangGraph mechanics and deterministic mock path. Add one typed decision result returned by DeepSeek at each decision point: initially it contains assessment, route, and either a question or candidate action; after a simulated event it contains parsed event facts, reassessment, and a candidate action. Existing nodes map these fields onto bounded LangGraph branches, and deterministic policy gates remain authoritative.

**Tech Stack:** Python 3.11+, LangGraph 1.x, Pydantic 2.x, `urllib.request` DeepSeek client, pytest.

## Global Constraints

- Change the Python LangGraph agent under `order-rescue-agent/` only.
- Keep the React Observatory and its mock event source separate and unchanged.
- Keep input validation, evidence construction, contact-policy enforcement, interrupts/checkpointing, recovery-policy enforcement, and final status construction deterministic.
- Do not add external tools or real-world side effects. Recommendations remain unexecuted.
- Use DeepSeek only when explicitly enabled with `--llm`; retain deterministic mock reasoning otherwise.
- Use typed structured output and registered enums for routes, hypotheses, intents, and actions.
- Validate evidence references against the evidence available in the current iteration.
- Preserve the raw reply as evidence; represent ambiguous intent as `UNKNOWN` rather than guessing.
- The LLM may select only an allowed route. LangGraph retains fixed routing, and deterministic gates decide whether the selected route can proceed.
- A model timeout, invalid JSON, invalid enum, or unsupported evidence reference must stop the decision safely with a visible error/escalation outcome. Do not silently switch from DeepSeek to the mock reasoner when `--llm` was requested.

---

## File Map

- `order-rescue-agent/agent/schemas.py`: add route/stage enums and the validated structured decision model.
- `order-rescue-agent/agent/state.py`: retain the structured decision between graph nodes and across the event resume.
- `order-rescue-agent/agent/reasoning.py`: define the decision-provider interface and DeepSeek structured decision request; preserve the existing assessment API and deterministic mock behavior.
- `order-rescue-agent/agent/nodes.py`: consume the initial decision and resumed decision in the existing nodes; keep policy and state mechanics deterministic.
- `order-rescue-agent/agent/graph.py`: inject the decision-capable reasoner into assessment and reply parsing; rebuild event evidence before the resumed decision; route only via fixed conditional edges.
- `order-rescue-agent/demo.py`: keep `--llm` opt-in and make the decision route visible in CLI output.
- `order-rescue-agent/README.md`: document the naive decision contract, route limits, and fail-closed LLM behavior.
- `order-rescue-agent/tests/test_reasoning.py`: cover structured provider requests and response validation using the existing fake transport pattern.
- `order-rescue-agent/tests/test_flow.py`: cover route mapping, event resume, and deterministic policy enforcement with a fake decision provider.

## Task 1: Define the structured decision contract

**Files:**
- Modify: `order-rescue-agent/agent/schemas.py`
- Modify: `order-rescue-agent/agent/state.py`
- Test: `order-rescue-agent/tests/test_reasoning.py`

**Interfaces:**
- Add `DecisionStage(StrEnum)` with `INITIAL` and `AFTER_EVENT`.
- Add `DecisionRoute(StrEnum)` with `ASK`, `WAIT_FOR_EVENT`, and `PROPOSE_RECOVERY`.
- Add `DecisionTarget(StrEnum)` with `BUYER`, `SELLER`, and `OPS`.
- Add `AgentDecision(DomainModel)` with fields `stage: DecisionStage`, `assessment: Assessment`, `route: DecisionRoute`, `target: DecisionTarget | None`, `information_request: InformationRequest | None`, `buyer_intent: BuyerIntent | None`, `parsed_facts: dict[str, str]`, `proposed_action: Action | None`, `rationale: str | None`, and `evidence_refs: list[str]`.
- Add `llm_decision: AgentDecision | None` to `AgentState`.

- [ ] **Step 1: Add contract validation tests**

Add these contract cases in `tests/test_reasoning.py`; import the named schema types from `agent.schemas` and import `ValidationError` from Pydantic:

```python
def test_agent_decision_accepts_initial_buyer_question():
    decision = AgentDecision(
        stage=DecisionStage.INITIAL,
        assessment=Assessment(
            hypothesis=Hypothesis.TEMP_AVAILABILITY_CONFLICT,
            confidence=Confidence.MEDIUM,
            missing_information=["buyer_intent"],
            evidence_refs=["OR-001:courier-note"],
            summary="Buyer intent is unknown.",
        ),
        route=DecisionRoute.ASK,
        target=DecisionTarget.BUYER,
        information_request=InformationRequest(
            question="Do you still want delivery?",
            purpose="Confirm buyer intent.",
        ),
    )
    assert decision.route is DecisionRoute.ASK


def test_agent_decision_accepts_unknown_after_event_intent():
    decision = AgentDecision(
        stage=DecisionStage.AFTER_EVENT,
        assessment=Assessment(
            hypothesis=Hypothesis.BUYER_INTENT_UNCERTAIN,
            confidence=Confidence.LOW,
            missing_information=["buyer_intent"],
            evidence_refs=["OR-001:event:BUYER_REPLY:1"],
            summary="The reply is ambiguous.",
        ),
        route=DecisionRoute.PROPOSE_RECOVERY,
        buyer_intent=BuyerIntent.UNKNOWN,
        proposed_action=Action.ESCALATE_REVIEW,
        rationale="Intent remains unclear.",
    )
    assert decision.buyer_intent is BuyerIntent.UNKNOWN


def test_agent_decision_rejects_unregistered_route():
    payload = {
        "stage": "INITIAL",
        "assessment": {
            "hypothesis": "TEMP_AVAILABILITY_CONFLICT",
            "confidence": "MEDIUM",
            "missing_information": ["buyer_intent"],
            "evidence_refs": ["OR-001:courier-note"],
            "summary": "Buyer intent is unknown.",
        },
        "route": "CALL_ANY_NODE",
        "target": "BUYER",
        "information_request": {
            "question": "Do you still want delivery?",
            "purpose": "Confirm buyer intent.",
            "simulated": True,
        },
    }
    with pytest.raises(ValidationError):
        AgentDecision.model_validate(payload)
```

Do not include any real API key in tests.

- [ ] **Step 2: Run the focused contract tests**

Run: `cd order-rescue-agent && .venv/bin/python -m pytest tests/test_reasoning.py -q`
Expected: the new tests fail until the enum/model definitions are added, then pass.

- [ ] **Step 3: Add the enums, model, and state field**

Implement the exact types listed above, using `Field(default_factory=dict)` for `parsed_facts` and `Field(default_factory=list)` for `evidence_refs`. Keep `DomainModel`'s `extra="forbid"` behavior. Do not put conditional policy decisions in this model.

- [ ] **Step 4: Re-run the focused contract tests**

Run: `cd order-rescue-agent && .venv/bin/python -m pytest tests/test_reasoning.py -q`
Expected: PASS; unsupported enum strings raise Pydantic validation errors.

- [ ] **Step 5: Commit the contract**

```bash
git add order-rescue-agent/agent/schemas.py order-rescue-agent/agent/state.py order-rescue-agent/tests/test_reasoning.py
git commit -m "feat: define structured agent decision contract"
```

## Task 2: Add a staged structured decision call

**Files:**
- Modify: `order-rescue-agent/agent/reasoning.py`
- Test: `order-rescue-agent/tests/test_reasoning.py`

**Interfaces:**
- Define `DecisionReasoner(Protocol)` with `decide(context: DeliveryContext, evidence: list[Evidence], *, stage: DecisionStage, case_input: BiCaseInput | None = None, case_event: CaseEvent | None = None) -> AgentDecision`.
- Implement `DeepSeekReasoner.decide(...)` with the same signature. Keep `DeepSeekReasoner.assess(...) -> Assessment` working for existing callers.
- Initial-stage results may route to `ASK`, `WAIT_FOR_EVENT`, or `PROPOSE_RECOVERY`; the corresponding question/target or candidate action must be present.
- After-event results must include buyer/event extraction, an updated assessment, and a candidate action. The route must be `PROPOSE_RECOVERY` for this naive version.

- [ ] **Step 1: Add fake-transport tests for both stages**

Extend the existing transport-injection tests with one fake JSON response for `INITIAL`/`ASK` and one for `AFTER_EVENT`/`PROPOSE_RECOVERY`. A fake transport should decode the request body, record it, and return the standard chat-completion envelope:

```python
def fake_transport(response_json, captured):
    def send(url, *, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["request"] = json.loads(body)
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps(response_json)},
            }]
        }
    return send
```

Assert the URL is `https://api.deepseek.com/chat/completions`, request `stream` is false, the stage and raw event are present in the user payload when supplied, and the returned object is an `AgentDecision`.

- [ ] **Step 2: Add rejection tests for unsafe model results**

With fake transport responses, assert `decide` raises a sanitized `RuntimeError` when JSON is malformed, the route/action is outside the schema, a required route field is missing, or an evidence reference is not in the current evidence list. Assert the error text never contains the authorization header or a supplied test secret.

- [ ] **Step 3: Implement the decision request and validation**

Build a compact stage-specific prompt from the observable case input, current evidence, and delayed event only. Request the `AgentDecision` JSON shape, validate it with Pydantic, enforce the stage-specific required fields, and reject evidence references absent from the current evidence. Keep deterministic policy evaluation out of the prompt result.

- [ ] **Step 4: Preserve the existing assessment method**

Keep `assess(...)` returning `Assessment` for current tests and callers. The new graph path uses `decide(...)` only when the injected reasoner provides it; deterministic callers continue to use `assess(...)`.

- [ ] **Step 5: Run focused provider tests**

Run: `cd order-rescue-agent && .venv/bin/python -m pytest tests/test_reasoning.py -q`
Expected: PASS with fake transport only; no live DeepSeek request is made.

- [ ] **Step 6: Commit the provider**

```bash
git add order-rescue-agent/agent/reasoning.py order-rescue-agent/tests/test_reasoning.py
git commit -m "feat: add structured DeepSeek decision calls"
```

## Task 3: Wire decisions into the bounded LangGraph flow

**Files:**
- Modify: `order-rescue-agent/agent/nodes.py`
- Modify: `order-rescue-agent/agent/graph.py`
- Modify: `order-rescue-agent/agent/state.py`
- Test: `order-rescue-agent/tests/test_flow.py`

**Interfaces:**
- `assess_case(state, reasoner=None)` calls `decide(..., stage=INITIAL)` when supported; otherwise it keeps the current `assess(...)` path.
- `parse_buyer_reply(state, reasoner=None)` runs after event evidence is rebuilt, calls `decide(..., stage=AFTER_EVENT, case_event=...)` when supported, and otherwise keeps deterministic parsing.
- `plan_information(state)` maps an `AgentDecision.route` to the existing boolean/target fields, while enforcing the current one-question limit and contact eligibility.
- `generate_question(state)` uses `AgentDecision.information_request` when provided; template behavior remains for the mock path.
- `propose_recovery(state)` uses the validated `AgentDecision.proposed_action` when present; otherwise it keeps existing deterministic proposal logic.

- [ ] **Step 1: Add fake decision-provider flow tests**

Create a fake provider implementing `decide(...)` that returns a valid initial `ASK` decision and an after-event `PROPOSE_RECOVERY` decision. Assert the graph pauses after the first decision, resumes with the supplied event, invokes the second decision only after event evidence has been built, stores the parsed buyer intent, and reaches the recovery-policy node with the candidate action.

- [ ] **Step 2: Test route and policy boundaries**

Add flow cases proving a non-permitted contact policy prevents `generate_question`, an LLM `ASK` result cannot bypass the existing question limit, and a candidate action rejected by deterministic recovery policy cannot become a permitted final recommendation. Keep the policy implementation unchanged.

- [ ] **Step 3: Build delayed-event evidence before LLM parsing**

After `wait_for_buyer`, route through `build_evidence` before `parse_buyer_reply`. Update `build_evidence` to add the resumed raw event/reply as evidence even before its intent is parsed. This ensures the resumed LLM call sees the full updated evidence pack and the raw event.

- [ ] **Step 4: Wire initial and resumed decisions through state**

Pass the injected reasoner to `parse_buyer_reply` from `create_graph`. It calls `decide(..., stage=AFTER_EVENT, case_event=...)` with the rebuilt evidence, then stores the structured decision and applies its parsed intent/facts to the context/evidence. Make `assess_case` use that stored assessment instead of making a third model call. The initial `assess_case` call uses `stage=INITIAL`.

- [ ] **Step 5: Map only allowlisted routes to graph edges**

Update `_after_planning` and the corresponding node outputs so `ASK`/`WAIT_FOR_EVENT` pass through `contact_policy_gate`, while `PROPOSE_RECOVERY` goes to `propose_recovery`. Keep the graph's edge destinations fixed in `graph.py`; never accept a model-provided node name.

- [ ] **Step 6: Re-run focused flow tests**

Run: `cd order-rescue-agent && .venv/bin/python -m pytest tests/test_flow.py tests/test_bi_contract.py -q`
Expected: PASS; old mock flow remains functional, LLM route cannot skip gates, and resume produces one post-event decision.

- [ ] **Step 7: Commit the graph integration**

```bash
git add order-rescue-agent/agent/nodes.py order-rescue-agent/agent/graph.py order-rescue-agent/agent/state.py order-rescue-agent/tests/test_flow.py
git commit -m "feat: route LangGraph through bounded LLM decisions"
```

## Task 4: Expose the naive flow in the CLI and documentation

**Files:**
- Modify: `order-rescue-agent/demo.py`
- Modify: `order-rescue-agent/README.md`

**Interfaces:**
- Keep the existing CLI flags `--case`, `--auto`, `--reply`, and `--llm`.
- `--llm` constructs the decision-capable `DeepSeekReasoner`; without it the deterministic mock path remains active.
- CLI output labels the selected route, parsed event intent, candidate action, policy result, and final `Executed: no` status without printing secrets.

- [ ] **Step 1: Update CLI output for structured decisions**

Print concise decision fields from the state and final result. Keep buyer event text visible as the existing synthetic demo does. Do not print request headers, API key values, or full prompts.

- [ ] **Step 2: Update agent documentation**

Document the two decision points, the allowed routes, the deterministic contact/recovery gates, the DeepSeek opt-in command, and the rule that final recommendations are never executed. State that the React UI remains disconnected from the Python agent.

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check`
Expected: no whitespace errors; diff contains only Python agent files and `order-rescue-agent/README.md`.

- [ ] **Step 4: Commit CLI and documentation**

```bash
git add order-rescue-agent/demo.py order-rescue-agent/README.md
git commit -m "docs: describe naive LLM decision flow"
```
