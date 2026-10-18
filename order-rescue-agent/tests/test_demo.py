import pytest

from agent.fixtures import load_bi_case
from agent.graph import create_graph, thread_config
from demo import _show_decision


@pytest.mark.parametrize("case_id", ["OR-055", "OR-056"])
def test_preflight_outcome_does_not_display_a_selected_route(case_id, capsys):
    state = create_graph().invoke(load_bi_case(case_id), config=thread_config(case_id))

    _show_decision(state)

    output = capsys.readouterr().out
    assert "Selected route: not selected" in output
    assert "Selected route: PROPOSE_RECOVERY" not in output
