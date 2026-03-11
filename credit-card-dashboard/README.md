# Credit Card Dashboard

Standalone local-first dashboard for managing multiple credit card accounts with:

- balances and utilization
- reminders for payment due dates
- statement upload and pull requests
- approval-based payment workflow
- masked credentials stored in a local encrypted vault
- explicit multi-agent orchestration

## Architecture

Agents:

- `PortfolioRefreshAgent`
- `StatementPullAgent`
- `ReminderAgent`
- `PaymentExecutionAgent`
- `DashboardOrchestrator`

Security:

- credentials are stored only in a local encrypted vault file
- the vault uses `openssl` locally
- passwords are never written to plain JSON
- UI only shows masked credential hints

Important limitation:

- live bank/issuer login and real payment execution are not implemented in this first version
- pull and pay actions are modeled as safe workflow steps inside the app
- uploaded statements and approved payments still work end to end within the site

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

## Commands

```bash
PYTHONPATH=src python3 -m credit_card_dashboard serve-ui --host 127.0.0.1 --port 8010
PYTHONPATH=src python3 -m credit_card_dashboard refresh
```
