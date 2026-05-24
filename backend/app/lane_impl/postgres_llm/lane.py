from __future__ import annotations

from app.models import Case, LaneResult


def run(case: Case, *, live_llm: bool = False) -> LaneResult:
    from app.lanes import run_postgres_llm_lane, run_postgres_llm_lane_live

    return run_postgres_llm_lane_live(case) if live_llm else run_postgres_llm_lane(case)
