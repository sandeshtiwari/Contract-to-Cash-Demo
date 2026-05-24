-- The Postgres + LLM lane intentionally owns this glue in application code.

SELECT *
FROM c2c_exception_cases
WHERE tenant_id = $1 AND case_id = $2;

SELECT *
FROM contract_clause_chunks
WHERE tenant_id = $1
  AND contract_id = $2
  AND status = 'active'
ORDER BY embedding <=> $3
LIMIT 6;

SELECT *
FROM revenue_policy_chunks
WHERE tenant_id = $1
  AND status = 'active'
ORDER BY embedding <=> $2
LIMIT 6;

INSERT INTO pg_c2c_adjustment_proposals (
  proposal_id,
  tenant_id,
  case_id,
  proposal_state,
  proposed_billing_adjustment_cents,
  proposed_revenue_adjustment_cents,
  decision,
  reason,
  evidence_json
) VALUES ($1, $2, $3, 'pending_review', $4, $5, $6, $7, $8);
