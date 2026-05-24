from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from agents import Agent, ModelSettings, Runner, trace
from pydantic import BaseModel, Field

from .config import get_settings


class ContractDecision(BaseModel):
    decision: str = Field(description="One of the allowed contract-to-cash decision ids.")
    billing_adjustment_cents: int | None = None
    revenue_adjustment_cents: int | None = None
    reason: str = Field(description="Short business-readable reason.")
    requires_approval: bool = False
    reason_codes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class LlmRun:
    content: dict[str, Any]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    elapsed_ms: int
    model: str
    sdk: str
    trace_id: str
    request_count: int


def openai_available() -> bool:
    return bool(get_settings().openai_api_key)


def run_contract_to_cash_llm(*, lane: str, payload: dict[str, Any], prompt: str) -> LlmRun:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    start = time.perf_counter()
    agent = Agent(
        name=f"{lane} contract-to-cash agent",
        model=settings.agent_model,
        instructions=_system_prompt(lane),
        output_type=ContractDecision,
        model_settings=ModelSettings(include_usage=True),
    )

    agent_input = json.dumps(
        {
            "operator_prompt": prompt,
            "lane": lane,
            "payload": payload,
        },
        ensure_ascii=False,
    )

    with trace(
        "Synapsor Contract-to-Cash Demo",
        group_id=f"contract-to-cash:{lane}",
        metadata={"lane": lane, "model": settings.agent_model, "sdk": "openai-agents"},
    ) as agent_trace:
        result = Runner.run_sync(agent, agent_input, max_turns=2)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    content = _content_from_output(result.final_output)
    usage = _combine_usage(result.raw_responses)
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    total_tokens = int(usage.get("total_tokens", 0)) or input_tokens + output_tokens
    return LlmRun(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
        model=settings.agent_model,
        sdk="OpenAI Agents SDK",
        trace_id=getattr(agent_trace, "trace_id", "") or "",
        request_count=int(usage.get("requests", 0)),
    )


def _system_prompt(lane: str) -> str:
    if lane.startswith("Synapsor"):
        return """
You are a contract-to-cash exception agent using a Synapsor capability payload.

Return only JSON with:
- decision
- billing_adjustment_cents
- revenue_adjustment_cents
- reason
- requires_approval
- reason_codes

Use only the compact payload. Trust Synapsor evidence handles, hidden session bindings, and DB-owned settlement policy. Do not plan approval, commit, merge, tenant filtering, or replay in the prompt.
""".strip()
    return f"""
You are a contract-to-cash exception agent running in the {lane} lane.

Return only a JSON object with these fields:
- decision: string
- billing_adjustment_cents: integer or null
- revenue_adjustment_cents: integer or null
- reason: short business-readable sentence
- requires_approval: boolean
- reason_codes: array of strings

Do not include markdown. Use the provided payload as the only business context.
The decision must be one of:
- adjustment_required
- no_adjustment_required
- reclass_adjustment_required
- billing_hold_required
- no_billing_adjustment_but_revenue_schedule_required
- human_review_required
Respect these controls:
- Billing adjustments above $2,500 require billing manager approval.
- Revenue adjustments above $5,000 require controller approval.
- High-risk signals require human review.
- Upfront billing does not by itself mean immediate revenue.
- Usage overage above a contract auto-bill threshold requires written approval if the clause says so.
- For the Synapsor lane, trust evidence handles and session-bound ids as database-owned authority.
- For the Postgres lane, assume the application assembled the raw context and must own proposal/audit/replay glue.
""".strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            value = json.loads(cleaned[start : end + 1])
        else:
            value = {"reason": cleaned}
    return value if isinstance(value, dict) else {"reason": str(value)}


def _content_from_output(output: Any) -> dict[str, Any]:
    if isinstance(output, ContractDecision):
        return output.model_dump()
    if isinstance(output, BaseModel):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    return _parse_json_object(str(output or "{}"))


def _combine_usage(raw_responses: list[Any]) -> dict[str, int]:
    totals = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for response in raw_responses:
        usage = getattr(response, "usage", None)
        if usage is None:
            continue
        totals["requests"] += int(getattr(usage, "requests", 0) or 1)
        totals["input_tokens"] += int(getattr(usage, "input_tokens", 0) or 0)
        totals["output_tokens"] += int(getattr(usage, "output_tokens", 0) or 0)
        totals["total_tokens"] += int(getattr(usage, "total_tokens", 0) or 0)
    return totals
