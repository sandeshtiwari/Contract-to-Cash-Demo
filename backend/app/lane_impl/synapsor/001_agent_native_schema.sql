CREATE TABLE customers (
  customer_id VARCHAR PRIMARY KEY,
  tenant_id VARCHAR,
  customer_name VARCHAR
) WITH PROFILE hot_state;

CREATE TABLE contracts (
  contract_id VARCHAR PRIMARY KEY,
  tenant_id VARCHAR,
  customer_id VARCHAR,
  contract_number VARCHAR,
  status VARCHAR
) WITH PROFILE hot_state;

CREATE TABLE invoices (
  invoice_id VARCHAR PRIMARY KEY,
  tenant_id VARCHAR,
  customer_id VARCHAR,
  contract_id VARCHAR,
  invoice_number VARCHAR,
  status VARCHAR,
  total_amount_cents INT64
) WITH PROFILE hot_state;

CREATE TABLE c2c_exception_cases (
  id VARCHAR PRIMARY KEY,
  case_id VARCHAR,
  tenant_id VARCHAR,
  customer_id VARCHAR,
  contract_id VARCHAR,
  invoice_id VARCHAR,
  close_period VARCHAR,
  case_type VARCHAR,
  status VARCHAR,
  risk_level VARCHAR,
  assigned_to VARCHAR,
  summary VARCHAR
) WITH PROFILE hot_state;

CREATE TABLE contract_clause_chunks (
  chunk_id VARCHAR PRIMARY KEY,
  tenant_id VARCHAR,
  contract_id VARCHAR,
  amendment_id VARCHAR,
  clause_type VARCHAR,
  title VARCHAR,
  status VARCHAR,
  effective_from VARCHAR,
  effective_to VARCHAR,
  body VARCHAR
) WITH (
  profile = 'searchable_knowledge',
  lexical_index = 'body',
  vector_index = 'body',
  filter_keys = 'tenant_id,contract_id,clause_type,status',
  zone_map = 'tenant_id,contract_id,clause_type,status'
);

CREATE TABLE revenue_policy_chunks (
  chunk_id VARCHAR PRIMARY KEY,
  tenant_id VARCHAR,
  policy_id VARCHAR,
  topic VARCHAR,
  status VARCHAR,
  effective_from VARCHAR,
  effective_to VARCHAR,
  allowed_role VARCHAR,
  body VARCHAR
) WITH (
  profile = 'searchable_knowledge',
  lexical_index = 'body',
  vector_index = 'body',
  filter_keys = 'tenant_id,topic,status,allowed_role',
  zone_map = 'tenant_id,topic,status'
);

CREATE TABLE c2c_adjustment_proposals (
  id VARCHAR PRIMARY KEY,
  tenant_id VARCHAR,
  case_id VARCHAR,
  customer_id VARCHAR,
  contract_id VARCHAR,
  invoice_id VARCHAR,
  close_period VARCHAR,
  proposal_state VARCHAR,
  proposed_billing_adjustment_cents INT64,
  proposed_revenue_adjustment_cents INT64,
  proposed_journal_entry_json VARCHAR,
  proposed_invoice_credit_json VARCHAR,
  decision VARCHAR,
  reason VARCHAR,
  reviewer VARCHAR,
  reviewed_at VARCHAR
) WITH PROFILE hot_state;

CREATE TABLE c2c_audit_events (
  id INT,
  tenant_id VARCHAR,
  principal VARCHAR,
  capability VARCHAR,
  resource VARCHAR,
  action VARCHAR,
  payload VARCHAR
) WITH (
  profile = 'audit_log',
  compact_after = '1 day',
  hot_window = '30 days',
  retention = '365 days',
  zone_map = 'tenant_id,action'
);

CREATE HYBRID INDEX contract_clause_chunks_body_hidx
ON contract_clause_chunks(body);

CREATE HYBRID INDEX revenue_policy_chunks_body_hidx
ON revenue_policy_chunks(body);

ANALYZE HYBRID INDEX contract_clause_chunks_body_hidx;
ANALYZE HYBRID INDEX revenue_policy_chunks_body_hidx;
