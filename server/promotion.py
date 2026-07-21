from __future__ import annotations

from typing import Literal

PromotionRoute = Literal["stable", "experimental"]

STABLE_ROUTE: PromotionRoute = "stable"
EXPERIMENTAL_ROUTE: PromotionRoute = "experimental"
EXPERIMENTAL_PROMOTION_GATES = frozenset(
    {
        "contracts",
        "physics_fixtures",
        "actor_motion",
        "browser",
        "download",
        "accessibility",
    }
)


def require_stable_cache_eligibility(
    *,
    route_label: str,
    receipt_verified: bool,
    passed_gates: frozenset[str],
) -> None:
    if route_label not in {STABLE_ROUTE, EXPERIMENTAL_ROUTE}:
        raise ValueError("stable cache promotion requires an explicit route label")
    if not receipt_verified:
        raise ValueError("stable cache promotion requires a verified receipt")
    if route_label == EXPERIMENTAL_ROUTE:
        missing = sorted(EXPERIMENTAL_PROMOTION_GATES - passed_gates)
        if missing:
            raise ValueError(
                "experimental route is missing stable promotion gates: "
                + ", ".join(missing)
            )
