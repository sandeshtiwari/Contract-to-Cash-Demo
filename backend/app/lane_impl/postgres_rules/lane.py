from __future__ import annotations

from app.lanes import run_rules_lane
from app.models import Case, LaneResult


def run(case: Case, *, live_llm: bool = False) -> LaneResult:
    return run_rules_lane(case)
