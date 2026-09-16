"""Budget enforcement for one run: tokens, money, calls and wall-clock time."""

from __future__ import annotations

import time

from regent.core.models import Budget, Usage


class BudgetExceeded(RuntimeError):
    """A hard ceiling of the mandate was reached. The run stops here."""

    def __init__(self, dimension: str, limit: float, actual: float) -> None:
        self.dimension = dimension
        self.limit = limit
        self.actual = actual
        super().__init__(f"budget exceeded on {dimension}: {actual} > {limit}")


class BudgetMeter:
    """Accumulates usage and raises as soon as a ceiling is crossed."""

    def __init__(self, budget: Budget) -> None:
        self._budget = budget
        self._usage = Usage()
        self._started = time.monotonic()

    @property
    def usage(self) -> Usage:
        """Everything spent so far."""
        return self._usage

    @property
    def budget(self) -> Budget:
        """The ceilings being enforced."""
        return self._budget

    def elapsed_s(self) -> float:
        """Seconds since the meter was created."""
        return time.monotonic() - self._started

    def remaining_usd(self) -> float:
        """Money still available, never negative."""
        return max(0.0, self._budget.max_usd - self._usage.usd)

    def check_time(self) -> None:
        """Raise when the wall-clock budget is gone."""
        elapsed = self.elapsed_s()
        if elapsed > self._budget.max_duration_s:
            raise BudgetExceeded("duration_s", self._budget.max_duration_s, round(elapsed, 1))

    def charge(self, usage: Usage) -> None:
        """Add *usage* and enforce every ceiling."""
        self._usage = self._usage.add(usage)
        b, u = self._budget, self._usage
        checks: tuple[tuple[str, float, float], ...] = (
            ("llm_calls", b.max_llm_calls, u.llm_calls),
            ("tool_calls", b.max_tool_calls, u.tool_calls),
            ("input_tokens", b.max_input_tokens, u.input_tokens),
            ("output_tokens", b.max_output_tokens, u.output_tokens),
            ("usd", b.max_usd, u.usd),
        )
        for dimension, limit, actual in checks:
            if actual > limit:
                raise BudgetExceeded(dimension, limit, actual)
        self.check_time()
