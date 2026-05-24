# Implementation Notes

## Seed Cases

| Case | Story | Expected lane lesson |
| --- | --- | --- |
| `C2C-1001` | Acme mid-quarter Analytics upgrade plus unapplied SLA credit | Main demo: LLM interprets amendment and SLA clause; Synapsor governs evidence and staged write |
| `C2C-1002` | BetaCloud clean renewal | Rules-only lane succeeds |
| `C2C-1003` | Northstar side-letter concession | Rules lane punts; LLM needed for side-letter allocation |
| `C2C-1004` | MedNova usage overage approval | Math is easy, contract approval language controls billability |
| `C2C-1005` | OmniWorks annual upfront billing | Billing and revenue recognition are different |

## Measured Demo Metrics

The backend computes live token estimates from the actual payload shapes used in the three lanes. Synapsor saves input tokens by returning compact slots, reason codes, selected `SEARCH ... USING HYBRID(...)` evidence, field aliases, and evidence handles. Hidden tenant, principal, current case, current customer, current contract, current invoice, current branch, and close-period bindings are DB/session state, not model prompt text. Postgres + LLM receives larger app-assembled context: raw rows, more policies, approval rules, proposal glue, and replay scaffolding.

## Safety Boundary Shown

The Synapsor lane never mutates production data directly. It creates a write proposal shaped like:

```text
wrp://c2c/<case_id>/<digest>
```

The UI then shows automatic branch staging, settlement policy, diff, merge outcome, and replay capability as database-owned execution state. The Synapsor SQL artifacts, not Python application glue, define the context, capabilities, write proposal target, allowed columns, audit sink, and branch/write lifecycle.

Low-risk read-only decisions are also shown. The BetaCloud clean-renewal case is auto-approved by a Synapsor capability rule because the invoice matches the contract, the revenue schedule is ratable, and no adjustment/write is needed. The output evidence modal shows the auto-approval lifecycle and audit artifact.

The lane result also carries an app-glue LOC architecture metric. This counts application-owned integration code, not Synapsor SQL/capability definitions. In the current demo numbers, Synapsor uses 54 app-glue LOC versus 318 for Postgres + LLM, a 264 LOC reduction, because context binding, evidence selection, branch/write lifecycle, settlement policy, audit, and replay are represented as DB-owned capability/state rather than app workflow code.

## Synapsor Syntax Refresh

The demo SQL mirrors the current agent-native syntax guide:

- hybrid evidence lookup is shown as `SEARCH ... USING HYBRID(table.column)` inside the agent context,
- read capabilities declare `RETURNS JSON`, `PROFILE MINIMAL`, `FIELD ALIASES`, and `INLINE EVIDENCE handles_only`,
- proposal capabilities declare visible args, hidden session bindings, `LOOKUP`, `TENANT`, allowed `COLUMNS`, audit, and summary template,
- schema files include `NOT NULL`, foreign-key constraints, tenant security policies, and resource redaction policy examples,
- the technical panel shows the Synapsor lane `.sql` artifacts, including `CREATE BRANCH`, `USE BRANCH`, `PROPOSE AGENT CAPABILITY`, `CREATE SETTLEMENT POLICY`, `SETTLE WRITE`, `AUTO APPROVE`, `AUTO COMMIT`, `AUTO MERGE`, `DIFF BRANCH`, `READ RESOURCE`, `SHOW HYBRID PLAN INDEX`, `REPLAY AGENT RUN`, historical branch creation, and `DIFF TABLE ... BETWEEN AS OF ... AND CURRENT`.

## Runnable LLM Mode

The final guided step runs live OpenAI Agents SDK calls for:

- `Synapsor + LLM`
- `Postgres + pgvector + LLM`

The rules lane stays local by design. Live usage replaces estimated input/output tokens when the Agents SDK response includes usage metadata. The UI reports the SDK model request in the lane trace, while the lane-level tool-call and DB-trip counts remain the product-architecture comparison.
