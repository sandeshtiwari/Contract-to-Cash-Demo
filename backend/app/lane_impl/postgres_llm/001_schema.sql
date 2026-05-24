CREATE TABLE c2c_exception_cases (
  case_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  contract_id TEXT NOT NULL,
  invoice_id TEXT NOT NULL,
  close_period TEXT NOT NULL,
  case_type TEXT NOT NULL,
  status TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  summary TEXT NOT NULL
);

CREATE TABLE contract_clause_chunks (
  chunk_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  contract_id TEXT NOT NULL,
  clause_type TEXT NOT NULL,
  status TEXT NOT NULL,
  body TEXT NOT NULL,
  embedding vector(384)
);

CREATE TABLE revenue_policy_chunks (
  chunk_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  status TEXT NOT NULL,
  allowed_role TEXT NOT NULL,
  body TEXT NOT NULL,
  embedding vector(384)
);

CREATE TABLE pg_c2c_adjustment_proposals (
  proposal_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  proposal_state TEXT NOT NULL,
  proposed_billing_adjustment_cents BIGINT,
  proposed_revenue_adjustment_cents BIGINT,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
