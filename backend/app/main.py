from __future__ import annotations

from dataclasses import asdict
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import ROOT
from .data import CASES, POLICIES, get_case
from .lanes import postgres_llm_payload, run_all_lanes, synapsor_context_payload
from .models import cents
from .synapsor_remote import SYNAPSOR_REMOTE


app = FastAPI(title="Synapsor Contract-to-Cash Exception Agent Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5177", "http://localhost:5177"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_synapsor_sql_artifacts() -> str:
    base = ROOT / "backend" / "app" / "lane_impl" / "synapsor"
    files = ["001_agent_native_schema.sql", "002_capabilities.sql"]
    return "\n\n-- ============================================================\n\n".join(
        (base / file_name).read_text() for file_name in files
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "synapsor_remote": "enabled" if SYNAPSOR_REMOTE.enabled else "disabled"}


@app.post("/api/reset")
def reset_demo_data() -> dict[str, str]:
    try:
        SYNAPSOR_REMOTE.reset()
    except Exception as exc:
        return {
            "status": "remote_pending",
            "message": f"Visible demo state is reset, but hosted Synapsor is still unavailable: {type(exc).__name__}. Retry after the service resumes.",
        }
    return {
        "status": "seeded",
        "message": "Remote Synapsor schema/capabilities and local visible run state were reset to seed data.",
    }


@app.get("/api/cases")
def list_cases() -> list[dict[str, object]]:
    return [
        {
            "case_id": case.case_id,
            "customer": case.customer,
            "case_type": case.case_type,
            "risk": case.risk,
            "status": case.status,
            "summary": case.summary,
            "lane_story": case.lane_story,
            "expected_decision": case.expected_decision,
            "expected_billing_adjustment": cents(case.expected_billing_adjustment_cents),
            "expected_revenue_adjustment": cents(case.expected_revenue_adjustment_cents),
        }
        for case in CASES
    ]


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str) -> dict[str, object]:
    try:
        case = get_case(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc

    return {
        "case": asdict(case),
        "compact_synapsor_payload": synapsor_context_payload(case),
        "policies": [asdict(policy) for policy in POLICIES],
    }


@app.get("/api/cases/{case_id}/agent-preview")
def agent_preview(case_id: str) -> dict[str, object]:
    try:
        case = get_case(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc
    return {"case_id": case.case_id, "agent_view": _agent_view(case)}


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str, live_llm: bool = Query(default=False)) -> dict[str, object]:
    try:
        case = get_case(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc

    results = [asdict(result) for result in run_all_lanes(case, live_llm=live_llm)]
    by_lane = {result["lane"]: result for result in results}
    postgres_tokens = int(by_lane["postgres_llm"]["input_tokens"])
    synapsor_tokens = int(by_lane["synapsor_llm"]["input_tokens"])
    savings = postgres_tokens - synapsor_tokens
    savings_pct = round((savings / postgres_tokens) * 100, 1) if postgres_tokens else 0

    return {
        "case_id": case.case_id,
        "prompt": case.prompt,
        "results": results,
        "live_llm": live_llm,
        "agent_view": _agent_view(case),
        "transparency": {
            "run_type": "comparison_report",
            "persistent_data_mutated": False,
            "hidden_backend_steps": [],
            "note": (
                "Running this demo creates a comparison report. It does not secretly modify seed data. "
                "Synapsor branch/proposal/settlement entries are shown as the DB-native lifecycle the demo is proving."
            ),
        },
        "token_savings": {
            "input_tokens_saved": savings,
            "input_reduction_percent": savings_pct,
            "synapsor_input_tokens": synapsor_tokens,
            "postgres_llm_input_tokens": postgres_tokens,
        },
    }


@app.get("/api/synapsor/capability")
def synapsor_capability() -> dict[str, str]:
    return {"sql": _load_synapsor_sql_artifacts()}


def _agent_view(case) -> dict[str, object]:
    syn_payload = synapsor_context_payload(case)
    pg_payload = postgres_llm_payload(case)
    return {
        "synapsor": {
            "title": "Compact governed packet",
            "summary": "The AI sees compact case slots, selected hybrid-search evidence, reason codes, aliases, evidence handles, and a note that Synapsor owns settlement.",
            "items": [
                f"Customer problem: {case.summary}",
                f"Invoice total: {cents(case.invoice_total_cents)}",
                f"Expected total: {cents(case.expected_invoice_total_cents)}",
                f"Evidence handles: {len(syn_payload['handles'])}",
                "Hidden DB bindings are not sent to the model",
                "Settlement policy is not sent as app workflow instructions",
                "Response aliases: d, r, ev",
                f"Reason codes: {', '.join(case.reason_codes)}",
            ],
            **_raw_text_with_metrics("Synapsor + LLM", case.prompt, syn_payload),
        },
        "postgres": {
            "title": "Large app-assembled context",
            "summary": "The AI sees raw rows, contract snippets, policy chunks, approval rules, proposal glue, and app-managed replay state.",
            "items": [
                "Raw case, invoice, invoice lines, usage, credits, and revenue rows",
                "Contract/policy chunks selected by app-owned pgvector/text-search glue",
                "Approval rules and proposal table instructions",
                "Application-owned tenant filters, evidence assembly, and replay notes",
            ],
            **_raw_text_with_metrics("Postgres + pgvector + LLM", case.prompt, pg_payload),
        },
        "rules": {
            "title": "No AI context",
            "summary": "The rules lane does not call the model. It only runs known deterministic checks.",
            "items": [
                "Invoice total checks",
                "Simple line comparisons",
                "Known thresholds",
                "Human review fallback for messy language",
            ],
            **_text_with_metrics(
                "Rules-only lane does not call an LLM.\n"
                "It reads deterministic rows and applies known checks:\n"
                "- invoice total checks\n"
                "- simple line comparisons\n"
                "- known thresholds\n"
                "- fallback to human review for messy language"
            ),
        },
    }


def _raw_text_with_metrics(lane: str, prompt: str, payload: dict[str, object]) -> dict[str, object]:
    text = _agent_raw_text(lane, prompt, payload)
    return _text_with_metrics(text)


def _text_with_metrics(text: str) -> dict[str, object]:
    return {
        "raw_text": text,
        "char_count": len(text),
        "word_count": len(text.split()),
    }


def _agent_raw_text(lane: str, prompt: str, payload: dict[str, object]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return (
        f"LANE: {lane}\n"
        f"OPERATOR QUESTION: {prompt}\n\n"
        "MODEL INSTRUCTION:\n"
        "Return JSON with decision, invoice adjustment, revenue adjustment, reason, approval flag, and reason codes.\n\n"
        "PAYLOAD SENT TO MODEL:\n"
        f"{payload_json}"
    )


@app.get("/api/lane-sql")
def lane_sql() -> dict[str, dict[str, str]]:
    base = ROOT / "backend" / "app" / "lane_impl"
    lanes: dict[str, dict[str, str]] = {}
    for lane_dir in sorted(path for path in base.iterdir() if path.is_dir() and not path.name.startswith("__")):
        files: dict[str, str] = {}
        for sql_file in sorted(lane_dir.glob("*.sql")):
            files[sql_file.name] = sql_file.read_text()
        lanes[lane_dir.name] = files
    return lanes
