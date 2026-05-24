from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


LaneId = Literal["synapsor_llm", "postgres_llm", "postgres_rules"]


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    title: str
    body: str
    source: str
    handle: str


@dataclass(frozen=True)
class InvoiceLine:
    product_id: str
    description: str
    amount_cents: int
    expected_cents: int | None = None


@dataclass(frozen=True)
class Usage:
    product_id: str
    metric_name: str
    included_quantity: int
    actual_quantity: int
    overage_quantity: int
    unit_price_cents: int
    billable_amount_cents: int


@dataclass(frozen=True)
class RevenueSchedule:
    obligation: str
    period: str
    planned_revenue_cents: int
    recognized_revenue_cents: int
    source: str


@dataclass(frozen=True)
class Case:
    case_id: str
    customer: str
    customer_id: str
    contract_id: str
    invoice_id: str
    close_period: str
    case_type: str
    risk: str
    status: str
    summary: str
    lane_story: str
    prompt: str
    invoice_total_cents: int
    expected_invoice_total_cents: int
    expected_decision: str
    expected_billing_adjustment_cents: int
    expected_revenue_adjustment_cents: int
    requires_approval: bool
    reason_codes: list[str]
    invoice_lines: list[InvoiceLine]
    usage: list[Usage] = field(default_factory=list)
    revenue_schedule: list[RevenueSchedule] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    risk_signals: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class LaneResult:
    lane: LaneId
    title: str
    decision: str
    billing_adjustment_cents: int | None
    revenue_adjustment_cents: int | None
    reason: str
    risk_level: str
    requires_approval: bool
    tool_calls: int
    db_round_trips: int
    app_glue_lines: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    evidence_items: int
    proposal_created: bool
    branch_created: bool
    replay_available: bool
    evidence_handles: list[str]
    evidence_details: list[dict[str, Any]]
    reason_codes: list[str]
    payload_breakdown: dict[str, int]
    architecture_notes: list[str]
    approval: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


def cents(value: int | None) -> str:
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value) / 100:,.2f}"
