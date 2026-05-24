CREATE AGENT CONTEXT c2c.exception_context
ROOT c2c_exception_cases AS c
LOOKUP c.id = SESSION current_case_id
BIND tenant_id FROM SESSION tenant_id
INCLUDE customers AS customer ON c.customer_id = customer.customer_id
INCLUDE contracts AS contract ON c.contract_id = contract.contract_id
INCLUDE invoices AS invoice ON c.invoice_id = invoice.invoice_id
OUTPUT SLOTS
  case_id AS c.id,
  customer_id AS c.customer_id,
  contract_id AS c.contract_id,
  invoice_id AS c.invoice_id,
  close_period AS c.close_period,
  case_type AS c.case_type,
  risk_level AS c.risk_level,
  status AS c.status
EVIDENCE ON;

CREATE AGENT CAPABILITY c2c.review_exception_context
DESCRIPTION 'Retrieve compact governed contract-to-cash exception context and evidence'
ARG question VARCHAR REQUIRED
HIDDEN tenant_id FROM SESSION tenant_id
HIDDEN principal FROM SESSION principal
HIDDEN current_case_id FROM SESSION current_case_id
HIDDEN current_customer_id FROM SESSION current_customer_id
HIDDEN current_contract_id FROM SESSION current_contract_id
HIDDEN current_invoice_id FROM SESSION current_invoice_id
HIDDEN close_period FROM SESSION close_period
USE CONTEXT c2c.exception_context
EXECUTION READ ONLY
TOKEN BUDGET MAX OUTPUT TOKENS 3200, MAX INLINE EVIDENCE ITEMS 8,
             MAX REASON COUNT 8, PREFER HANDLES
PLAN
DEFAULT DECISION needs_review

SCAN case_row FROM c2c_exception_cases AS c
WHERE FIELD c.tenant_id = ARG tenant_id
  AND FIELD c.id = ARG current_case_id
OUTPUT case_id = FIELD c.id,
       customer_id = FIELD c.customer_id,
       contract_id = FIELD c.contract_id,
       invoice_id = FIELD c.invoice_id,
       close_period = FIELD c.close_period,
       case_type = FIELD c.case_type,
       risk_level = FIELD c.risk_level,
       status = FIELD c.status,
       summary = FIELD c.summary

SCAN customer_row FROM customers AS cust
WHERE FIELD cust.tenant_id = ARG tenant_id
  AND FIELD cust.customer_id = ARG current_customer_id
OUTPUT customer_id = FIELD cust.customer_id,
       customer_name = FIELD cust.customer_name

SCAN contract_row FROM contracts AS con
WHERE FIELD con.tenant_id = ARG tenant_id
  AND FIELD con.contract_id = ARG current_contract_id
OUTPUT contract_id = FIELD con.contract_id,
       contract_number = FIELD con.contract_number,
       status = FIELD con.status

SCAN invoice_row FROM invoices AS inv
WHERE FIELD inv.tenant_id = ARG tenant_id
  AND FIELD inv.invoice_id = ARG current_invoice_id
OUTPUT invoice_id = FIELD inv.invoice_id,
       invoice_number = FIELD inv.invoice_number,
       status = FIELD inv.status,
       total_amount_cents = FIELD inv.total_amount_cents

HYBRID_SEARCH contract_clause_hits
  TABLE contract_clause_chunks
  COLUMN body
  QUERY ARG question
  LIMIT 6
  FILTER tenant_id = ARG tenant_id,
         contract_id = ARG current_contract_id,
         status = 'active'

HYBRID_SEARCH revenue_policy_hits
  TABLE revenue_policy_chunks
  COLUMN body
  QUERY ARG question
  LIMIT 6
  FILTER tenant_id = ARG tenant_id,
         status = 'active'

RULE no_adjustment_required REASON invoice_matches_contract
  WHEN FIELD c.case_type = 'Clean renewal'
  TERMINAL

RULE needs_review REASON contract_to_cash_exception_context_prepared
  WHEN STEP_COUNT case_row > 0
  TERMINAL

PAYLOAD case = STEP_OUTPUT case_row,
        customer = STEP_OUTPUT customer_row,
        contract = STEP_OUTPUT contract_row,
        invoice = STEP_OUTPUT invoice_row,
        contract_clause_hits = STEP_OUTPUT contract_clause_hits,
        revenue_policy_hits = STEP_OUTPUT revenue_policy_hits

EVIDENCE case = STEP_OUTPUT case_row,
         customer = STEP_OUTPUT customer_row,
         contract = STEP_OUTPUT contract_row,
         invoice = STEP_OUTPUT invoice_row,
         contract_clause_hits = STEP_OUTPUT contract_clause_hits,
         revenue_policy_hits = STEP_OUTPUT revenue_policy_hits
END PLAN
RETURNS JSON '{"type":"object","properties":{"decision":{},"reason_codes":{},"case":{},"customer":{},"contract":{},"invoice":{},"contract_clause_hits":{},"revenue_policy_hits":{},"evidence":{}}}'
PROFILE MINIMAL
FIELD ALIASES decision AS d, reason_codes AS r, evidence AS ev
INLINE EVIDENCE handles_only;

CREATE AGENT CAPABILITY c2c.propose_adjustment
DESCRIPTION 'Create a branch-staged contract-to-cash adjustment proposal for one exception case'
ARG adjustment_id VARCHAR REQUIRED
ARG decision VARCHAR REQUIRED
ARG proposed_billing_adjustment_cents INT64 REQUIRED
ARG proposed_revenue_adjustment_cents INT64 REQUIRED
ARG proposed_journal_entry_json VARCHAR REQUIRED
ARG proposed_invoice_credit_json VARCHAR REQUIRED
ARG reason VARCHAR REQUIRED
ARG reviewed_at VARCHAR REQUIRED
HIDDEN tenant_id FROM SESSION tenant_id
HIDDEN principal FROM SESSION principal
HIDDEN current_case_id FROM SESSION current_case_id
USE CONTEXT c2c.exception_context
EXECUTION PROPOSAL
RETURNS JSON '{"type":"object","properties":{"proposal":{},"branch":{},"decision":{},"evidence_bundle":{}}}'
WRITE PROPOSAL TARGET c2c_adjustment_proposals
OPERATION UPDATE
LOOKUP id FROM ARG adjustment_id
TENANT tenant_id FROM BINDING tenant_id
COLUMNS proposal_state FROM VALUE 'proposed',
        proposed_billing_adjustment_cents FROM ARG proposed_billing_adjustment_cents,
        proposed_revenue_adjustment_cents FROM ARG proposed_revenue_adjustment_cents,
        proposed_journal_entry_json FROM ARG proposed_journal_entry_json,
        proposed_invoice_credit_json FROM ARG proposed_invoice_credit_json,
        decision FROM ARG decision,
        reason FROM ARG reason,
        reviewer FROM BINDING principal,
        reviewed_at FROM ARG reviewed_at
AUDIT c2c_audit_events
SUMMARY TEMPLATE 'Propose C2C adjustment for case {current_case_id}';

CREATE SETTLEMENT POLICY c2c.green_auto_settle
FOR CAPABILITY c2c.propose_adjustment
TARGET BRANCH main
AUTO APPROVE WHEN
  PAYLOAD trusted_after.decision = 'no_adjustment_required'
  AND PAYLOAD trusted_after.proposed_billing_adjustment_cents = 0
  AND PAYLOAD trusted_after.proposed_revenue_adjustment_cents = 0
AUTO COMMIT
AUTO MERGE
ELSE LEAVE PROPOSED;
