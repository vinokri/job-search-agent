# Credit Card Dashboard

Standalone local-first credit card operations site for six or more accounts with:

- portfolio balances and utilization
- payment reminders and due-date visibility
- statement request queue plus uploaded statement artifacts
- approval-gated payment lifecycle
- issuer-specific adapter metadata
- masked credentials stored only in a local encrypted vault
- explicit multi-agent orchestration with runtime and memory

## Architecture

### Agents

- `PortfolioRefreshAgent`
- `ReminderAgent`
- `StatementPullAgent`
- `PaymentExecutionAgent`
- `DashboardOrchestrator`

### Adapter Layer

Per-bank adapters live in `src/credit_card_dashboard/adapters.py`.

Each adapter declares:

- issuer key
- portal label
- statement workflow mode
- payment workflow mode
- whether local credentials are useful for statement/payment flows
- operator notes for the UI

Current adapters are included for:

- American Express
- Chase
- Citi
- Capital One
- Discover
- Bank of America

### Secret Handling

The secret model is local-only:

- encrypted secret payload: `data/secrets.vault`
- masked metadata only: `data/secrets.meta.json`

Design choices:

- cleartext passwords are never written to JSON files
- vault encryption uses local `openssl` with PBKDF2
- vault and metadata files are written with private file permissions when possible
- the UI displays only masked usernames and credential-ready status

### Workflow Model

Statement lifecycle:

1. queue a statement request
2. store connector-ready credentials locally if desired
3. download the statement from the issuer outside the app
4. upload the statement into the dashboard
5. the request is marked `completed_with_upload`

Payment lifecycle:

1. create a payment request
2. approve it in the dashboard
3. if credentials exist, the request becomes `approved_ready_for_confirmation`
4. confirm the payment against the issuer locally
5. mark it completed with a confirmation reference

This keeps the system safe: nothing is paid just because a form was submitted in the UI.

## Current Production-Grade Improvements

- issuer adapter registry per bank
- atomic JSON writes for runtime data
- separate encrypted vault and masked metadata store
- file-permission hardening for vault artifacts
- downloadable statement artifacts
- cleaner statement and payment lifecycle queues
- datalist-assisted account selection in the UI

## Important Limitation

This project is production-shaped, but it is still intentionally local-first and non-networked:

- it does not log into live issuer sites from this app
- it does not auto-download statements from issuers
- it does not execute real ACH/card payments
- it tracks and stages those actions safely for local confirmation

That limitation is deliberate because this repo is designed to keep secrets local and avoid external connectivity by default.

## Run

```bash
cd "/Users/vinodhkrishnamoorthy/Documents/New project/credit-card-dashboard"
./run.sh
```

Then open [http://127.0.0.1:8010](http://127.0.0.1:8010).

Manual equivalent:

```bash
cd "/Users/vinodhkrishnamoorthy/Documents/New project/credit-card-dashboard"
PYTHONPATH=src python3 -m credit_card_dashboard serve-ui --host 127.0.0.1 --port 8010
```

## Data

- `data/accounts.json`
- `data/runtime.json`
- `data/memory.json`
- `data/payment-requests.json`
- `data/statement-requests.json`
- `data/statements/index.json`
- `data/secrets.vault`
- `data/secrets.meta.json`

## Commands

```bash
PYTHONPATH=src python3 -m credit_card_dashboard serve-ui --host 127.0.0.1 --port 8010
PYTHONPATH=src python3 -m credit_card_dashboard refresh
```

## UI Flow

1. Refresh the portfolio runtime.
2. Add or edit card accounts.
3. Store masked credentials in the local vault.
4. Queue statement requests and upload statement PDFs or files.
5. Create payment requests.
6. Approve a payment request.
7. Confirm the payment outside the app with the bank.
8. Mark the payment completed with a reference.
