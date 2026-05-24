# Demo Report

Generated from the current seeded lane payloads.

| Case | Customer | Synapsor input tokens | Postgres + LLM input tokens | Saved | Reduction | Synapsor tool calls | Postgres tool calls | Rules lane |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `C2C-1001` | Acme Robotics | 2,449 | 6,478 | 4,029 | 62.2% | 2 | 13 | `human_review_required` |
| `C2C-1002` | BetaCloud | 1,845 | 5,282 | 3,437 | 65.1% | 1 | 10 | `no_adjustment_required` |
| `C2C-1003` | Northstar Health | 1,972 | 5,511 | 3,539 | 64.2% | 2 | 13 | `human_review_required` |
| `C2C-1004` | MedNova Labs | 1,963 | 5,492 | 3,529 | 64.3% | 2 | 13 | `human_review_required` |
| `C2C-1005` | OmniWorks | 1,957 | 5,442 | 3,485 | 64.0% | 2 | 13 | `human_review_required` |

Average input savings: about 3,604 tokens per run.

## Current Interpretation

The demo shows the intended three-lane contrast:

- Synapsor + LLM uses compact slots, evidence handles, and DB-owned capability semantics.
- Postgres + LLM reaches the same decision target, but pays for larger app-owned context and more tool calls.
- Rules-only is fast and token-free, but only succeeds on the clean renewal case and punts on messy contract language.

## Validation

- Backend API tests: `3 passed`
- Frontend production build: passed
