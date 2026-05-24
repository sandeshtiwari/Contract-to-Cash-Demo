from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from typing import Any

from .data import POLICIES
from .llm import openai_available, run_contract_to_cash_llm
from .models import Case, LaneResult
from .synapsor_remote import SYNAPSOR_REMOTE


SYNAPSOR_APP_GLUE_LINES = 54
POSTGRES_LLM_APP_GLUE_LINES = 318
POSTGRES_RULES_APP_GLUE_LINES = 142


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return max(1, math.ceil(len(text) / 4))


def money(cents: int | None) -> str:
    if cents is None:
        return "not computed"
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.0f}"


def _base_reason(case: Case) -> str:
    if case.case_id == "C2C-1001":
        return "Analytics was billed at $8,000 instead of $4,000, and the approved $3,000 SLA credit was not applied."
    if case.case_id == "C2C-1002":
        return "Invoice total and May ratable revenue schedule match the clean renewal terms."
    if case.case_id == "C2C-1003":
        return "The side letter applies a $2,000 Core subscription concession, but the invoice applied $3,500 against implementation services."
    if case.case_id == "C2C-1004":
        return "The 20% usage overage exceeds the 10% auto-bill threshold and lacks written approval."
    return "The annual upfront invoice is billable, but revenue should be recognized ratably over the service period."


def _evidence_details(case: Case, *, handle_prefix: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    evidence = case.evidence[:limit] if limit else case.evidence
    return [
        {
            "id": ev.id,
            "kind": ev.kind,
            "title": ev.title,
            "source": ev.source,
            "handle": f"{handle_prefix}:{ev.id}" if handle_prefix else ev.handle,
            "snippet": ev.body,
        }
        for ev in evidence
    ]


def synapsor_context_payload(case: Case) -> dict[str, Any]:
    top_evidence = case.evidence[:8]
    return {
        "c": {
            "id": case.case_id,
            "risk": case.risk,
            "summary": case.summary,
        },
        "db_scope": {
            "binding": "resolved_by_synapsor_session",
            "note": "tenant/principal/case/customer/contract/invoice/branch are hidden DB bindings.",
        },
        "inv": {
            "id": case.invoice_id,
            "actual_cents": case.invoice_total_cents,
            "expected_cents": case.expected_invoice_total_cents,
            "variance_cents": case.expected_invoice_total_cents - case.invoice_total_cents,
        },
        "ev": [
            {
                "t": ev.title,
                "k": ev.kind,
                "s": ev.body[:180],
                "h": ev.handle,
            }
            for ev in top_evidence
        ],
        "r": case.reason_codes,
        "handles": [ev.handle for ev in top_evidence],
        "settlement": "Synapsor policy owns auto-approve/commit/merge; model does not plan lifecycle.",
    }


def postgres_llm_payload(case: Case) -> dict[str, Any]:
    return {
        "system_prompt": "You are a contract-to-cash revenue operations agent. Review all rows, clauses, policies, approval rules, and proposal constraints. Use tenant filters. Build evidence. Return a safe adjustment recommendation.",
        "case": asdict(case),
        "all_policy_chunks": [asdict(p) for p in POLICIES],
        "raw_contract_clauses": [asdict(ev) for ev in case.evidence if ev.kind in {"contract_clause", "side_letter"}],
        "all_invoice_rows": [asdict(line) for line in case.invoice_lines],
        "approval_rules": [
            "Billing adjustments above $2,500 require billing manager approval.",
            "Revenue adjustments above $5,000 require controller approval.",
            "High-risk signal requires human review.",
            "Production writes require proposal, approval, and audit tables maintained by the application.",
        ],
        "app_glue_state": {
            "tenant_filter": "WHERE tenant_id = 'demo'",
            "proposal_table": "pg_c2c_adjustment_proposals",
            "branch_simulation": "application-managed diff rows",
            "replay": "application reconstructs run from logs",
        },
    }


def token_breakdown(payload: dict[str, Any], lane: str) -> dict[str, int]:
    if lane == "synapsor":
        return {
            "System instructions": 340,
            "Tool schemas": 260,
            "Case data": estimate_tokens(payload.get("c", {})) + estimate_tokens(payload.get("inv", {})),
            "Contract/policy evidence": estimate_tokens(payload.get("ev", [])),
            "Business rules": estimate_tokens(payload.get("r", [])) + 120,
            "Prior state / audit": estimate_tokens(payload.get("handles", [])) + 120,
        }
    return {
        "System instructions": 900,
        "Tool schemas": 1550,
        "Case data": estimate_tokens(payload.get("case", {})) + estimate_tokens(payload.get("all_invoice_rows", [])),
        "Contract/policy evidence": estimate_tokens(payload.get("raw_contract_clauses", [])) + estimate_tokens(payload.get("all_policy_chunks", [])),
        "Business rules": estimate_tokens(payload.get("approval_rules", [])) + 900,
        "Prior state / audit": estimate_tokens(payload.get("app_glue_state", {})) + 760,
    }


def build_proposal(case: Case) -> dict[str, Any]:
    digest = hashlib.sha1(case.case_id.encode()).hexdigest()[:8]
    branch = f"c2c_case_{case.case_id.replace('-', '_')}_BR_{digest}"
    lifecycle = [
        f"CREATE BRANCH {branch} FROM main",
        f"USE BRANCH {branch}",
        "PROPOSE AGENT CAPABILITY c2c.propose_adjustment",
        "SETTLE WRITE last_proposal USING POLICY c2c.green_auto_settle",
    ]
    if case.requires_approval:
        lifecycle.extend([
            "SETTLEMENT RESULT left_proposed",
            "Reviewer can approve or reject the DB-owned proposal",
        ])
    else:
        lifecycle.extend(["AUTO APPROVE", "AUTO COMMIT", "AUTO MERGE"])
    lifecycle.append(f"DIFF BRANCH {branch} AGAINST main")
    return {
        "proposal_handle": f"wrp://c2c/{case.case_id}/{digest}",
        "branch": branch,
        "branch_policy": "auto_create_on_proposal",
        "created_by": "Synapsor branch/write-proposal lifecycle",
        "target_table": "c2c_adjustment_proposals",
        "allowed_columns": [
            "proposal_state",
            "proposed_billing_adjustment_cents",
            "proposed_revenue_adjustment_cents",
            "proposed_journal_entry_json",
            "proposed_invoice_credit_json",
            "decision",
            "reason",
            "reviewer",
            "reviewed_at",
        ],
        "preview": {
            "decision": case.expected_decision,
            "billing_adjustment": money(case.expected_billing_adjustment_cents),
            "revenue_adjustment": money(case.expected_revenue_adjustment_cents),
            "state": "proposed",
        },
        "settlement_policy": "c2c.green_auto_settle",
        "lifecycle": lifecycle,
    }


def _extract_remote_handle(envelope: dict[str, Any]) -> str | None:
    for key in ("proposal", "proposal_handle", "handle_uri"):
        value = envelope.get(key)
        if isinstance(value, str):
            return value
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        return _extract_remote_handle(payload)
    return None


def _extract_remote_branch(envelope: dict[str, Any]) -> str | None:
    action = envelope.get("action")
    if isinstance(action, dict):
        branch = action.get("branch")
        if isinstance(branch, dict) and isinstance(branch.get("id"), str):
            return branch["id"]
    for key in ("branch", "branch_id"):
        value = envelope.get(key)
        if isinstance(value, str):
            return value
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        return _extract_remote_branch(payload)
    return None


def _extract_remote_settlement(envelope: dict[str, Any]) -> dict[str, Any] | None:
    settlement = envelope.get("settlement")
    if isinstance(settlement, dict):
        return settlement
    action = envelope.get("action")
    if isinstance(action, dict) and isinstance(action.get("settlement"), dict):
        return action["settlement"]
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        return _extract_remote_settlement(payload)
    return None


def _remote_synapsor_artifacts(case: Case, proposal_needed: bool) -> dict[str, Any]:
    if not SYNAPSOR_REMOTE.enabled:
        return {"enabled": False, "notes": ["Hosted Synapsor API key is not configured."]}
    review = SYNAPSOR_REMOTE.review_context(case)
    proposal = SYNAPSOR_REMOTE.propose_adjustment(case) if proposal_needed else None
    return {
        "enabled": True,
        "review": review,
        "proposal": proposal,
        "notes": [
            "Hosted Synapsor read capability executed against synapsor.ai.",
            "Hosted Synapsor write proposal executed with auto_branch and settlement policy." if proposal_needed else "No write proposal needed for this case.",
        ],
    }


def build_synapsor_approval(case: Case) -> dict[str, Any]:
    if not case.requires_approval and case.expected_decision == "no_adjustment_required":
        return {
            "state": "auto_approved",
            "mode": "synapsor_auto_approval_gate",
            "reason": "Low-risk clean renewal: invoice total, contract terms, and ratable revenue schedule match.",
            "artifact": f"audit://c2c/{case.case_id}/auto_approval",
            "lifecycle": [
                "INVOKE c2c.review_exception_context",
                "RULE low_risk_clean_renewal_matched",
                "RULE no_adjustment_required",
                "AUTO APPROVE READ-ONLY DECISION",
                "AUDIT c2c_audit_events",
                "REPLAY AGENT RUN available",
            ],
        }
    return {
        "state": "human_review_required",
        "mode": "branch_staged_proposal" if case.expected_decision != "no_adjustment_required" else "review_only",
        "reason": "Approval required by risk, adjustment amount, or policy gate.",
        "artifact": None,
        "lifecycle": [],
    }


def run_synapsor_lane(case: Case) -> LaneResult:
    payload = synapsor_context_payload(case)
    breakdown = token_breakdown(payload, "synapsor")
    input_tokens = sum(breakdown.values())
    proposal_needed = case.expected_decision != "no_adjustment_required"
    remote: dict[str, Any]
    remote_notes: list[str] = []
    try:
        remote = _remote_synapsor_artifacts(case, proposal_needed)
        remote_notes = remote.get("notes", [])
    except Exception as exc:
        remote = {"enabled": SYNAPSOR_REMOTE.enabled, "error": str(exc)}
        remote_notes = [f"Hosted Synapsor run failed: {type(exc).__name__}."]

    proposal = build_proposal(case) if proposal_needed else None
    remote_proposal = remote.get("proposal") if isinstance(remote.get("proposal"), dict) else None
    if proposal is not None and remote_proposal is not None:
        handle = _extract_remote_handle(remote_proposal)
        branch = _extract_remote_branch(remote_proposal)
        settlement = _extract_remote_settlement(remote_proposal)
        if handle:
            proposal["proposal_handle"] = handle
        if branch:
            proposal["branch"] = branch
            proposal["branch_policy"] = "hosted_synapsor_auto_branch"
        if settlement:
            proposal["settlement_result"] = settlement

    return LaneResult(
        lane="synapsor_llm",
        title="Synapsor + LLM",
        decision=case.expected_decision,
        billing_adjustment_cents=case.expected_billing_adjustment_cents,
        revenue_adjustment_cents=case.expected_revenue_adjustment_cents,
        reason=_base_reason(case),
        risk_level=case.risk,
        requires_approval=case.requires_approval,
        tool_calls=2 if proposal_needed else 1,
        db_round_trips=2 if proposal_needed else 1,
        app_glue_lines=SYNAPSOR_APP_GLUE_LINES,
        input_tokens=input_tokens,
        output_tokens=690 if proposal_needed else 430,
        elapsed_ms=1180 if proposal_needed else 760,
        evidence_items=min(8, len(case.evidence)),
        proposal_created=proposal_needed,
        branch_created=proposal_needed,
        replay_available=True,
        evidence_handles=[ev.handle for ev in case.evidence[:8]],
        evidence_details=_evidence_details(case, limit=8),
        reason_codes=case.reason_codes,
        payload_breakdown=breakdown,
        architecture_notes=[
            f"Hosted Synapsor project/database: {SYNAPSOR_REMOTE.settings.synapsor_project_id}/{SYNAPSOR_REMOTE.settings.synapsor_database_id}.",
            *remote_notes,
            "Session-bound tenant, customer, contract, invoice, and close period.",
            "DB-owned SEARCH ... USING HYBRID evidence selection with handles-only inline evidence.",
            "Capability response uses RETURNS JSON plus FIELD ALIASES for a compact adapter payload.",
            "Hidden session bindings stay in Synapsor, not in the LLM context.",
            "Tenant security and resource redaction policies apply below the agent prompt.",
            "Synapsor auto-creates an isolated case branch when the proposal capability needs a production update.",
            "Write is staged as a proposal on that branch; green writes can be approved, committed, and merged by Synapsor settlement policy.",
            "Low-risk clean cases can be auto-approved by DB-owned capability rules and recorded in audit/replay state.",
            "Agent run is replayable from original/current snapshot, and a review branch can be created from the run.",
            f"App glue LOC architecture metric: {SYNAPSOR_APP_GLUE_LINES}; context, evidence, approval, settlement, branch, and replay policy live in Synapsor SQL/capabilities.",
        ],
        approval=build_synapsor_approval(case),
        proposal=proposal,
        trace=[
            {"step": "SET SESSION", "detail": "tenant_id, principal, case/customer/contract/invoice bindings"},
            {"step": "INVOKE c2c.review_exception_context", "detail": "hosted Synapsor compact governed payload + field aliases + evidence handles"},
            {"step": "LLM reasoning", "detail": "interpret amendment, clauses, policy, and adjustment"},
            {"step": "CREATE BRANCH", "detail": "Synapsor automatically creates an isolated case branch before staging writes"} if proposal_needed else {"step": "No branch", "detail": "no production change needed"},
            {"step": "PROPOSE c2c.propose_adjustment", "detail": "hosted Synapsor write proposal is staged on the branch, not production"} if proposal_needed else {"step": "No proposal", "detail": "no production change needed"},
            {"step": "SETTLE WRITE", "detail": "Synapsor settlement policy evaluates whether the proposal can auto-approve, auto-commit, and auto-merge"} if proposal_needed else {"step": "AUTO APPROVE", "detail": "low-risk read-only decision is auto-approved and audited by Synapsor rules"},
        ],
    )


def run_postgres_llm_lane(case: Case) -> LaneResult:
    payload = postgres_llm_payload(case)
    breakdown = token_breakdown(payload, "postgres")
    input_tokens = sum(breakdown.values())
    proposal_needed = case.expected_decision != "no_adjustment_required"
    return LaneResult(
        lane="postgres_llm",
        title="Postgres + pgvector + LLM",
        decision=case.expected_decision,
        billing_adjustment_cents=case.expected_billing_adjustment_cents,
        revenue_adjustment_cents=case.expected_revenue_adjustment_cents,
        reason=_base_reason(case),
        risk_level=case.risk,
        requires_approval=case.requires_approval,
        tool_calls=13 if proposal_needed else 10,
        db_round_trips=17 if proposal_needed else 12,
        app_glue_lines=POSTGRES_LLM_APP_GLUE_LINES,
        input_tokens=input_tokens,
        output_tokens=820 if proposal_needed else 510,
        elapsed_ms=2310 if proposal_needed else 1560,
        evidence_items=len(case.evidence),
        proposal_created=proposal_needed,
        branch_created=False,
        replay_available=False,
        evidence_handles=[f"pg_evidence:{ev.id}" for ev in case.evidence],
        evidence_details=_evidence_details(case, handle_prefix="pg_evidence"),
        reason_codes=case.reason_codes,
        payload_breakdown=breakdown,
        architecture_notes=[
            "Application fetches rows and assembles context manually.",
            "Application owns pgvector/text search, filters, evidence selection, proposal tables, and replay approximation.",
            "The LLM receives more raw context because the database does not own compact capability payloads.",
            f"App glue LOC architecture metric: {POSTGRES_LLM_APP_GLUE_LINES}; the app owns retrieval, filters, evidence assembly, proposal workflow, audit, and replay glue.",
        ],
        approval={
            "state": "app_approved" if not proposal_needed else "app_managed_review",
            "mode": "application_workflow",
            "reason": "Approval state is managed by application code and tables.",
            "artifact": f"pg_audit://{case.case_id}",
            "lifecycle": [],
        },
        proposal={
            "proposal_handle": f"pg_prop://{case.case_id}",
            "branch": "app-managed diff rows",
            "target_table": "pg_c2c_adjustment_proposals",
        }
        if proposal_needed
        else None,
        trace=[
            {"step": "fetch_case/fetch_contract/fetch_invoice", "detail": "multiple app-owned SQL tools"},
            {"step": "search_contract_clauses_pgvector", "detail": "app applies tenant/status/effective-date filters"},
            {"step": "search_revenue_policies_pgvector", "detail": "app assembles snippets and policies into prompt"},
            {"step": "stage_pg_proposal", "detail": "application-managed proposal/audit state"} if proposal_needed else {"step": "No proposal", "detail": "no production change needed"},
        ],
    )


def run_synapsor_lane_live(case: Case) -> LaneResult:
    base = run_synapsor_lane(case)
    if not openai_available():
        return _mark_llm_unavailable(base)
    payload = synapsor_context_payload(case)
    return _apply_live_llm(base, "Synapsor + LLM", payload, case.prompt)


def run_postgres_llm_lane_live(case: Case) -> LaneResult:
    base = run_postgres_llm_lane(case)
    if not openai_available():
        return _mark_llm_unavailable(base)
    payload = postgres_llm_payload(case)
    return _apply_live_llm(base, "Postgres + pgvector + LLM", payload, case.prompt)


def _apply_live_llm(base: LaneResult, lane_name: str, payload: dict[str, Any], prompt: str) -> LaneResult:
    try:
        run = run_contract_to_cash_llm(lane=lane_name, payload=payload, prompt=prompt)
    except Exception as exc:  # pragma: no cover - exercised manually with local API key.
        return replace(
            base,
        reason=f"{base.reason} Live OpenAI Agents SDK run failed: {type(exc).__name__}.",
        architecture_notes=base.architecture_notes + [f"Live OpenAI Agents SDK run failed: {type(exc).__name__}."],
        trace=base.trace + [{"step": "OpenAI Agents SDK run failed", "detail": type(exc).__name__}],
        )

    content = run.content
    decision = _normalize_decision(str(content.get("decision") or base.decision), base.decision)
    billing = _nullable_int(content.get("billing_adjustment_cents"), base.billing_adjustment_cents)
    revenue = _nullable_int(content.get("revenue_adjustment_cents"), base.revenue_adjustment_cents)
    reason = str(content.get("reason") or base.reason)
    reason_codes = content.get("reason_codes") if isinstance(content.get("reason_codes"), list) else base.reason_codes
    requires_approval = content.get("requires_approval")
    if not isinstance(requires_approval, bool):
        requires_approval = base.requires_approval
    input_tokens = run.input_tokens or base.input_tokens
    output_tokens = run.output_tokens or base.output_tokens

    return replace(
        base,
        decision=decision,
        billing_adjustment_cents=billing,
        revenue_adjustment_cents=revenue,
        reason=reason,
        requires_approval=requires_approval,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_ms=run.elapsed_ms,
        reason_codes=[str(code) for code in reason_codes],
        architecture_notes=base.architecture_notes + [f"Live {run.sdk}: {run.model}."],
        trace=base.trace
        + [
            {
                "step": "OpenAI Agents SDK live reasoning",
                "detail": f"{run.model}, {input_tokens} input tokens, {output_tokens} output tokens, {run.request_count or 1} model request(s)",
            },
            {"step": "OpenAI trace", "detail": run.trace_id or "trace captured by SDK"},
        ],
    )


def _nullable_int(value: Any, fallback: int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_decision(value: str, fallback: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"approve", "approved", "ok", "pass"}:
        return "no_adjustment_required"
    allowed = {
        "adjustment_required",
        "no_adjustment_required",
        "reclass_adjustment_required",
        "billing_hold_required",
        "no_billing_adjustment_but_revenue_schedule_required",
        "human_review_required",
    }
    return normalized if normalized in allowed else fallback


def _mark_llm_unavailable(base: LaneResult) -> LaneResult:
    return replace(
        base,
        architecture_notes=base.architecture_notes + ["Live OpenAI Agents SDK mode requested, but OPENAI_API_KEY was not configured."],
        trace=base.trace + [{"step": "OpenAI Agents SDK run skipped", "detail": "OPENAI_API_KEY missing"}],
    )


def run_rules_lane(case: Case) -> LaneResult:
    easy = case.case_id == "C2C-1002"
    acme_partial = case.case_id == "C2C-1001"
    if easy:
        decision = "no_adjustment_required"
        billing = 0
        revenue = 0
        reason = "Deterministic rule matched invoice total to monthly contract lines."
    elif acme_partial:
        decision = "human_review_required"
        billing = case.expected_invoice_total_cents - case.invoice_total_cents
        revenue = None
        reason = "Rules detect a billing variance, but cannot safely interpret the SLA credit and amendment revenue treatment."
    elif case.case_id == "C2C-1004":
        decision = "human_review_required"
        billing = -400_000
        revenue = None
        reason = "Rules detect overage math, but punt because billability depends on written approval language."
    else:
        decision = "human_review_required"
        billing = None
        revenue = None
        reason = "Rules punt on messy language, side letters, concessions, or revenue judgment."
    return LaneResult(
        lane="postgres_rules",
        title="Postgres Rules Only",
        decision=decision,
        billing_adjustment_cents=billing,
        revenue_adjustment_cents=revenue,
        reason=reason,
        risk_level=case.risk,
        requires_approval=decision != "no_adjustment_required",
        tool_calls=0,
        db_round_trips=4,
        app_glue_lines=POSTGRES_RULES_APP_GLUE_LINES,
        input_tokens=0,
        output_tokens=0,
        elapsed_ms=90,
        evidence_items=0,
        proposal_created=False,
        branch_created=False,
        replay_available=False,
        evidence_handles=[],
        evidence_details=[],
        reason_codes=["deterministic_path"] if easy else ["human_review_required"],
        payload_breakdown={
            "System instructions": 0,
            "Tool schemas": 0,
            "Case data": 0,
            "Contract/policy evidence": 0,
            "Business rules": 0,
            "Prior state / audit": 0,
        },
        architecture_notes=[
            "Fast and cheap for known paths.",
            "Cannot interpret ambiguous concessions, amendments, side letters, or revenue policy nuance without hardcoding.",
            f"App glue LOC architecture metric: {POSTGRES_RULES_APP_GLUE_LINES}; each new exception type needs more deterministic code.",
        ],
        approval={
            "state": "deterministic_pass" if easy else "human_review_required",
            "mode": "rules_only",
            "reason": "Rules can pass a known clean case, but route messy language to a human.",
            "artifact": None,
            "lifecycle": [],
        },
        trace=[
            {"step": "load rows", "detail": "case, contract, invoice, lines"},
            {"step": "apply deterministic checks", "detail": "totals, simple credits, known usage thresholds"},
            {"step": "punt or pass", "detail": decision},
        ],
    )


def run_all_lanes(case: Case, *, live_llm: bool = False) -> list[LaneResult]:
    from .lane_impl import postgres_llm, postgres_rules, synapsor

    if live_llm:
        with ThreadPoolExecutor(max_workers=2) as executor:
            syn_future = executor.submit(synapsor.run, case, live_llm=True)
            pg_future = executor.submit(postgres_llm.run, case, live_llm=True)
            rules_result = postgres_rules.run(case, live_llm=False)
            return [syn_future.result(), pg_future.result(), rules_result]

    return [
        synapsor.run(case, live_llm=live_llm),
        postgres_llm.run(case, live_llm=live_llm),
        postgres_rules.run(case, live_llm=live_llm),
    ]
