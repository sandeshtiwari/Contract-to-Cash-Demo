from __future__ import annotations

import json
import time
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import ROOT, get_settings
from .data import CASES, POLICIES
from .models import Case


def sql_string(value: object) -> str:
    return "'" + str(value if value is not None else "").replace("'", "''") + "'"


class RemoteSynapsorClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        project_id: str,
        database_id: str,
        timeout_seconds: int = 45,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.project_id = project_id
        self.database_id = database_id
        self.timeout_seconds = timeout_seconds

    def execute(self, sql: str, *, session: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"sql": sql, "project_id": self.project_id, "database_id": self.database_id}
        if session:
            payload["session"] = session
        return self._request("POST", "/v1/sql", payload)

    def query(self, sql: str, *, session: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        response = self.execute(sql, session=session)
        results = response.get("results", [])
        if not results:
            return []
        return list(results[-1].get("result", {}).get("rows", []))

    def invoke_agent_capability(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        session: dict[str, Any],
        mode: str | None = None,
        trace_id: str | None = None,
        auto_branch: bool | None = None,
        response_envelope: bool = True,
        include_audit_trail: bool = True,
        settlement_policy: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability": capability,
            "arguments": arguments,
            "session": session,
            "response_envelope": response_envelope,
            "include_audit_trail": include_audit_trail,
        }
        if mode is not None:
            payload["mode"] = mode
        if trace_id is not None:
            payload["trace_id"] = trace_id
        if auto_branch is not None:
            payload["auto_branch"] = bool(auto_branch)
        if settlement_policy is not None:
            payload["settlement_policy"] = settlement_policy
        return self._request("POST", "/v1/agent/invoke", payload)

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        request_payload.setdefault("project_id", self.project_id)
        request_payload.setdefault("database_id", self.database_id)
        body = json.dumps(request_payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
            "X-Synapsor-Project-Id": self.project_id,
            "X-Synapsor-Database-Id": self.database_id,
        }
        last_error: Exception | None = None
        for attempt in range(4):
            request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw or "{}")
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    detail: Any = json.loads(raw or "{}")
                except json.JSONDecodeError:
                    detail = {"error": raw}
                message = detail.get("error") if isinstance(detail, dict) else None
                last_error = RuntimeError(f"Synapsor HTTP {exc.code}: {message or detail}")
                if exc.code not in {429, 503, 504} or attempt == 3:
                    raise last_error from exc
            except urllib.error.URLError as exc:
                last_error = RuntimeError(f"Synapsor request failed: {exc.reason}")
                if attempt == 3:
                    raise last_error from exc
            time.sleep(0.6 * (attempt + 1))
        raise RuntimeError(str(last_error or "Synapsor request failed"))


class SynapsorRemoteStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: RemoteSynapsorClient | None = None
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.synapsor_api_key)

    def db(self) -> RemoteSynapsorClient:
        if not self.settings.synapsor_api_key:
            raise RuntimeError("SYNAPSOR_SERVER_API_KEY or SYNAPSOR_API_KEY is required")
        with self._lock:
            if self._client is None:
                self._client = RemoteSynapsorClient(
                    base_url=self.settings.synapsor_url,
                    api_key=self.settings.synapsor_api_key,
                    project_id=self.settings.synapsor_project_id,
                    database_id=self.settings.synapsor_database_id,
                )
            return self._client

    def reset(self) -> None:
        if not self.enabled:
            return
        db = self.db()
        self._cleanup(db)
        base = ROOT / "backend" / "app" / "lane_impl" / "synapsor"
        self._execute_script(db, (base / "001_agent_native_schema.sql").read_text())
        self._seed(db)
        capabilities = (base / "002_capabilities.sql").read_text()
        capabilities = capabilities.replace("TARGET BRANCH main", f"TARGET BRANCH {self.settings.synapsor_database_id}")
        self._execute_script(db, capabilities)
        self._execute_script(
            db,
            f"""
            ALTER SETTLEMENT POLICY c2c.green_auto_settle SET TARGET BRANCH {self.settings.synapsor_database_id}
            AUTO APPROVE WHEN
              PAYLOAD trusted_after.decision = 'no_adjustment_required'
              AND PAYLOAD trusted_after.proposed_billing_adjustment_cents = 0
              AND PAYLOAD trusted_after.proposed_revenue_adjustment_cents = 0
            AUTO COMMIT
            AUTO MERGE
            ELSE LEAVE PROPOSED;
            """,
        )

    def review_context(self, case: Case) -> dict[str, Any]:
        return self.db().invoke_agent_capability(
            "c2c.review_exception_context",
            {"question": case.prompt},
            session=self.session(case),
            mode="read_only",
            trace_id=f"c2c_review_{case.case_id.replace('-', '_')}",
        )

    def propose_adjustment(self, case: Case) -> dict[str, Any]:
        return self.db().invoke_agent_capability(
            "c2c.propose_adjustment",
            {
                "adjustment_id": f"ADJ-{case.case_id}",
                "decision": case.expected_decision,
                "proposed_billing_adjustment_cents": case.expected_billing_adjustment_cents,
                "proposed_revenue_adjustment_cents": case.expected_revenue_adjustment_cents,
                "proposed_journal_entry_json": json.dumps({"memo": case.summary, "case_id": case.case_id}),
                "proposed_invoice_credit_json": json.dumps({"case_id": case.case_id, "amount_cents": case.expected_billing_adjustment_cents}),
                "reason": case.summary,
                "reviewed_at": datetime.now(UTC).isoformat(),
            },
            session=self.session(case),
            mode="propose_only",
            trace_id=f"c2c_propose_{case.case_id.replace('-', '_')}",
            auto_branch=True,
            settlement_policy="c2c.green_auto_settle",
        )

    def session(self, case: Case) -> dict[str, Any]:
        return {
            "tenant_id": "demo",
            "principal": "revops_agent_01",
            "session_id": f"c2c_{case.case_id}",
            "current_case_id": case.case_id,
            "current_customer_id": case.customer_id,
            "current_contract_id": case.contract_id,
            "current_invoice_id": case.invoice_id,
            "close_period": case.close_period,
            "snapshot_ts": 0,
        }

    def _cleanup(self, db: RemoteSynapsorClient) -> None:
        for statement in [
            "DROP AGENT CAPABILITY c2c.propose_adjustment;",
            "DROP AGENT CAPABILITY c2c.review_exception_context;",
            "DROP AGENT CONTEXT c2c.exception_context;",
            "DROP TABLE IF EXISTS c2c_audit_events;",
            "DROP TABLE IF EXISTS c2c_adjustment_proposals;",
            "DROP TABLE IF EXISTS revenue_policy_chunks;",
            "DROP TABLE IF EXISTS contract_clause_chunks;",
            "DROP TABLE IF EXISTS c2c_exception_cases;",
            "DROP TABLE IF EXISTS invoices;",
            "DROP TABLE IF EXISTS contracts;",
            "DROP TABLE IF EXISTS customers;",
        ]:
            try:
                db.execute(statement)
            except Exception:
                pass

    def _execute_script(self, db: RemoteSynapsorClient, script: str) -> None:
        for statement in [part.strip() for part in script.split(";") if part.strip()]:
            try:
                db.execute(statement + ";")
            except Exception as exc:
                if statement.upper().startswith("CREATE SETTLEMENT POLICY") and "already" in str(exc).lower():
                    continue
                raise

    def _seed(self, db: RemoteSynapsorClient) -> None:
        seen_customers: set[str] = set()
        seen_contracts: set[str] = set()
        seen_invoices: set[str] = set()
        seen_contract_chunks: set[str] = set()
        seen_policy_chunks: set[str] = set()
        for case in CASES:
            if case.customer_id not in seen_customers:
                db.execute(
                    "INSERT INTO customers VALUES "
                    f"({sql_string(case.customer_id)}, 'demo', {sql_string(case.customer)});"
                )
                seen_customers.add(case.customer_id)
            if case.contract_id not in seen_contracts:
                db.execute(
                    "INSERT INTO contracts VALUES "
                    f"({sql_string(case.contract_id)}, 'demo', {sql_string(case.customer_id)}, {sql_string(case.contract_id)}, 'active');"
                )
                seen_contracts.add(case.contract_id)
            if case.invoice_id not in seen_invoices:
                db.execute(
                    "INSERT INTO invoices VALUES "
                    f"({sql_string(case.invoice_id)}, 'demo', {sql_string(case.customer_id)}, {sql_string(case.contract_id)}, "
                    f"{sql_string(case.invoice_id)}, 'open', {case.invoice_total_cents});"
                )
                seen_invoices.add(case.invoice_id)
            db.execute(
                "INSERT INTO c2c_exception_cases VALUES "
                f"({sql_string(case.case_id)}, {sql_string(case.case_id)}, 'demo', {sql_string(case.customer_id)}, {sql_string(case.contract_id)}, "
                f"{sql_string(case.invoice_id)}, {sql_string(case.close_period)}, {sql_string(case.case_type)}, "
                f"{sql_string(case.status.lower())}, {sql_string(case.risk)}, 'revops_agent_01', {sql_string(case.summary)});"
            )
            db.execute(
                "INSERT INTO c2c_adjustment_proposals VALUES "
                f"({sql_string('ADJ-' + case.case_id)}, 'demo', {sql_string(case.case_id)}, {sql_string(case.customer_id)}, "
                f"{sql_string(case.contract_id)}, {sql_string(case.invoice_id)}, {sql_string(case.close_period)}, 'draft', "
                f"0, 0, '{{}}', '{{}}', 'pending', '', '', '');"
            )
            for evidence in case.evidence:
                if evidence.kind in {"contract_clause", "side_letter"} and evidence.id not in seen_contract_chunks:
                    db.execute(
                        "INSERT INTO contract_clause_chunks VALUES "
                        f"({sql_string(evidence.id)}, 'demo', {sql_string(case.contract_id)}, '', {sql_string(evidence.kind)}, "
                        f"{sql_string(evidence.title)}, 'active', '2026-01-01', '', {sql_string(evidence.body)});"
                    )
                    seen_contract_chunks.add(evidence.id)
        for policy in POLICIES:
            if policy.id in seen_policy_chunks:
                continue
            db.execute(
                "INSERT INTO revenue_policy_chunks VALUES "
                f"({sql_string(policy.id)}, 'demo', {sql_string(policy.source)}, {sql_string(policy.kind)}, 'active', "
                f"'2026-01-01', '', 'revops', {sql_string(policy.body)});"
            )
            seen_policy_chunks.add(policy.id)


SYNAPSOR_REMOTE = SynapsorRemoteStore()
