from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_case_queue_has_seeded_cases():
    response = client.get("/api/cases")
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) == 5
    assert cases[0]["case_id"] == "C2C-1001"


def test_three_lane_run_reports_synapsor_token_savings():
    response = client.post("/api/cases/C2C-1001/run")
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 3
    assert body["token_savings"]["input_tokens_saved"] > 0
    synapsor = next(result for result in body["results"] if result["lane"] == "synapsor_llm")
    assert synapsor["proposal_created"] is True
    assert synapsor["branch_created"] is True
    assert synapsor["replay_available"] is True
    assert synapsor["proposal"]["branch_policy"] in {"auto_create_on_proposal", "hosted_synapsor_auto_branch"}
    assert "CREATE BRANCH" in synapsor["proposal"]["lifecycle"][0]
    assert len(synapsor["evidence_details"]) == synapsor["evidence_items"]
    assert synapsor["evidence_details"][0]["handle"].startswith("evidence://")


def test_synapsor_payload_keeps_hidden_bindings_out_of_llm_context():
    response = client.get("/api/cases/C2C-1001")
    assert response.status_code == 200
    payload = response.json()["compact_synapsor_payload"]
    assert "session_bindings" not in payload
    assert payload["db_scope"]["binding"] == "resolved_by_synapsor_session"


def test_synapsor_sql_is_sql_first_and_includes_branch_lifecycle():
    response = client.get("/api/synapsor/capability")
    assert response.status_code == 200
    sql = response.json()["sql"]
    assert "CREATE AGENT CAPABILITY c2c.propose_adjustment" in sql
    assert "CREATE SETTLEMENT POLICY c2c.green_auto_settle" in sql
    assert "WRITE PROPOSAL TARGET c2c_adjustment_proposals" in sql
    assert "AUTO MERGE" in sql
    assert "AUTO APPROVE" in sql


def test_low_risk_synapsor_case_is_auto_approved():
    response = client.post("/api/cases/C2C-1002/run")
    assert response.status_code == 200
    synapsor = next(result for result in response.json()["results"] if result["lane"] == "synapsor_llm")
    assert synapsor["decision"] == "no_adjustment_required"
    assert synapsor["requires_approval"] is False
    assert synapsor["approval"]["state"] == "auto_approved"
    assert "AUTO APPROVE" in synapsor["approval"]["lifecycle"][3]
    assert synapsor["proposal_created"] is False


def test_unknown_case_returns_404():
    response = client.post("/api/cases/nope/run")
    assert response.status_code == 404
