# Synapsor Contract-to-Cash Exception Agent Demo

This is a runnable [Synapsor](https://synapsor.ai) Contract-to-Cash exception demo. It is isolated under `Synapsor analysis/contract_to_cash_synapsor_demo` and does not modify the Synapsor DBMS source tree.

It demonstrates three lanes for the same finance exception workflow:

- `Synapsor + LLM`: DBMS-owned context, hidden session bindings, hybrid evidence selection, evidence handles, token budget, branch-staged proposal, approval, and replay.
- `Postgres + pgvector + LLM`: same intelligence target, but the app owns context assembly, pgvector/text search glue, filtering, proposal state, audit, and replay approximation.
- `Postgres Rules Only`: fast and cheap for clean deterministic paths, but punts on side letters, amendments, usage approval language, and revenue judgment.

## Run

```bash
./run.sh
```

The app starts:

- Backend: `http://127.0.0.1:8017`
- Frontend: `http://127.0.0.1:5177`

The final walkthrough step runs the two LLM lanes through the OpenAI Agents SDK using `gpt-5-mini` by default. The demo loads `OPENAI_API_KEY` and the hosted Synapsor key from this project only.

## Hosted Synapsor

The Synapsor lane calls the hosted Synapsor runtime at `https://synapsor.ai`.
The API key stays in `backend/.env`, which is ignored by git.

Expected environment:

```bash
SYNAPSOR_URL=https://synapsor.ai
SYNAPSOR_PROJECT_ID=contract_to_cash
SYNAPSOR_DATABASE_ID=db_contract_to_cash_dev
SYNAPSOR_SERVER_API_KEY=...
```

The backend uses the installed Synapsor Python package against the hosted runtime:

```python
from synapsor import Synapsor

client = Synapsor("https://synapsor.ai", api_key="<synapsor_api_key>")
print(client.query("SELECT 1;"))
```

`POST /api/reset` drops any prior demo tables/capabilities in that hosted
database scope, loads the Contract-to-Cash schema, inserts seed cases, builds
hybrid indexes, and creates the Synapsor agent context/capabilities/settlement
policy. If the hosted service is still resuming, the endpoint returns
`remote_pending` and the UI can be retried after the runtime is available.

## Lane Code Layout

The three lanes are separated for inspection under:

- `backend/app/lane_impl/synapsor`
- `backend/app/lane_impl/postgres_llm`
- `backend/app/lane_impl/postgres_rules`

Initial SQL artifacts live beside each lane implementation. The Synapsor lane is intentionally SQL-first: `001_agent_native_schema.sql` defines DB-owned tables, indexes, policies, and redaction, while `002_capabilities.sql` defines the agent context, read capability, proposal capability, settlement policy, automatic case branch lifecycle, evidence reads, and replay commands.

## Test

```bash
cd backend
python -m pytest

cd ../frontend
npm run build
```

## What This Is

The Synapsor lane uses the hosted Synapsor API for the database-owned portion of
the demo: compact capability payloads, hybrid evidence selection, `RETURNS JSON`,
`FIELD ALIASES`, `PROFILE MINIMAL`, `INLINE EVIDENCE handles_only`, write
proposal handles, automatic branch staging for production-impacting proposals,
and settlement policy. Hidden tenant/case/customer/contract/invoice bindings
stay in Synapsor and are not sent to the LLM. Live reasoning is executed through
the OpenAI Agents SDK.
