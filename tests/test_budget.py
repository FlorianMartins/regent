import pytest

from regent.core.budget import BudgetExceeded, BudgetMeter
from regent.core.models import Budget, Usage


def test_charge_accumulates():
    meter = BudgetMeter(Budget(max_usd=1.0))
    meter.charge(Usage(usd=0.3, llm_calls=1))
    meter.charge(Usage(usd=0.3, llm_calls=1))
    assert meter.usage.usd == pytest.approx(0.6) and meter.usage.llm_calls == 2
    assert meter.remaining_usd() == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("budget", "usage", "dimension"),
    [
        (Budget(max_usd=0.5), Usage(usd=0.6), "usd"),
        (Budget(max_llm_calls=1), Usage(llm_calls=2), "llm_calls"),
        (Budget(max_tool_calls=1), Usage(tool_calls=2), "tool_calls"),
        (Budget(max_input_tokens=10), Usage(input_tokens=11), "input_tokens"),
        (Budget(max_output_tokens=10), Usage(output_tokens=11), "output_tokens"),
    ],
)
def test_ceilings(budget: Budget, usage: Usage, dimension: str):
    with pytest.raises(BudgetExceeded) as exc:
        BudgetMeter(budget).charge(usage)
    assert exc.value.dimension == dimension


def test_time_ceiling(monkeypatch: pytest.MonkeyPatch):
    meter = BudgetMeter(Budget(max_duration_s=1))
    monkeypatch.setattr(meter, "elapsed_s", lambda: 5.0)
    with pytest.raises(BudgetExceeded, match="duration"):
        meter.check_time()
