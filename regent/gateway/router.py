"""Model routing: a *tier* in the mandate becomes a concrete model at call time.

Why tiers and not model names in mandates: models change every quarter,
mandates should not. A tier is a promise about capability and cost; the
router keeps the mapping in one place and can degrade when a budget runs low.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Route(BaseModel):
    """The model chosen for one call."""

    model_config = ConfigDict(frozen=True)

    tier: str
    model: str
    degraded: bool = False
    """True when the router picked a cheaper tier than requested."""


DEFAULT_TIERS: dict[str, str] = {
    "fast": "claude-haiku-4-5",
    "balanced": "claude-sonnet-5",
    "deep": "claude-opus-5",
}

_ORDER = ("fast", "balanced", "deep")


class Router:
    """Resolve tiers to models, with cost-aware degradation."""

    def __init__(
        self, tiers: dict[str, str] | None = None, degrade_below_usd: float = 0.10
    ) -> None:
        self._tiers = dict(tiers or DEFAULT_TIERS)
        self._degrade_below_usd = degrade_below_usd
        for tier in _ORDER:
            if tier not in self._tiers:
                raise ValueError(f"router needs a model for tier '{tier}'")

    def resolve(self, tier: str, remaining_usd: float | None = None) -> Route:
        """Pick a model for *tier*, stepping down when the remaining budget is thin."""
        if tier not in self._tiers:
            raise ValueError(f"unknown model tier '{tier}' (known: {', '.join(self._tiers)})")
        chosen = tier
        if remaining_usd is not None and remaining_usd < self._degrade_below_usd:
            chosen = "fast"
        return Route(tier=chosen, model=self._tiers[chosen], degraded=chosen != tier)
