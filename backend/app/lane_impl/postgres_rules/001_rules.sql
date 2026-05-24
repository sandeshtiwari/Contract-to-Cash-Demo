-- Rules-only lane: fast known-path checks, no LLM.

SELECT
  c.case_id,
  CASE
    WHEN c.status <> 'Open' THEN 'ignore_closed_case'
    WHEN i.total_amount_cents = SUM(il.amount_cents) THEN 'invoice_lines_tie_out'
    ELSE 'human_review_required'
  END AS rule_decision
FROM c2c_exception_cases c
JOIN invoices i ON i.invoice_id = c.invoice_id AND i.tenant_id = c.tenant_id
JOIN invoice_lines il ON il.invoice_id = i.invoice_id AND il.tenant_id = i.tenant_id
WHERE c.tenant_id = $1 AND c.case_id = $2
GROUP BY c.case_id, c.status, i.total_amount_cents;

-- Messy language remains out of scope for the deterministic lane:
-- side letters, ambiguous concessions, usage approval clauses, and billing-vs-revenue judgment.
