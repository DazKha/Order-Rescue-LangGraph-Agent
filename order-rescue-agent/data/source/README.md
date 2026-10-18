# BI Workbook Alignment

The user supplied `order_rescue_simulation_cases_v0.1 (1).xlsx` from Downloads. The `README`, `Policy_Rules`, `Field_Dictionary`, `explain Field`, `Cases`, `Coverage`, and `Sources` sheets were inspected to align this agent.

The workbook itself is not copied into the repository. Sanitized derived artifacts are kept in separate files:

- `data/fixtures/bi_inputs.json` contains the 56 observable case inputs.
- `data/fixtures/bi_events.json` contains each later event and is loaded only after the graph pauses.
- `data/expected/bi_expected.json` contains BI's proposed labels for tests only; the graph and model do not load it.

The synthetic PII marker in OR-052 was redacted from the public fixture. The simulated R01-R22 policy and expected labels are treated as evaluation guidance, not verified carrier policy.
