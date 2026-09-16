# T212 Trading Control

This Cloudflare Worker is a tightly bounded Trading 212 **Demo/Practice** execution bridge.

## Current safety boundary

- The Trading 212 Demo base URL is hard-coded. There is no live-account switch.
- Credentials are Cloudflare secrets and must never be committed.
- Agent/read routes and the human approval route use separate bearer tokens.
- The only broker write is a fixed Demo market-order payload reconstructed from an approved proposal.
- A proposal must be approved with the exact phrase `APPROVE PAPER [trade ID] AS WRITTEN` before it can be submitted.
- Quantity is capped at 1 share for the initial smoke test.
- D1 atomically consumes each approval once. The Worker never retries an order POST automatically; an uncertain response becomes `UNKNOWN` for reconciliation.
- There is no generic proxy, cancellation route, sell route or automatic trading loop.

## Routes

Unauthenticated:

- `GET /health` — configuration state only; never returns secrets.

Authenticated with `Authorization: Bearer <T212_AGENT_TOKEN>`:

- `GET /t212/test` or `/t212/cash`
- `GET /t212/summary`
- `GET /t212/positions`
- `GET /t212/orders`
- `GET /t212/history/orders`
- `GET /t212/instruments`
- `GET /t212/exchanges`
- `POST /t212/proposals`
- `POST /t212/proposals/{tradeId}/execute`
- `GET /t212/proposals/{tradeId}/verify`

Authenticated with the human-only `T212_APPROVER_TOKEN`:

- `POST /t212/proposals/{tradeId}/approve`

## Required Cloudflare configuration

1. Deploy the default `wrangler.toml` first. It contains no D1 binding, so order execution is locked while read-only authentication is tested.
2. Add Worker secrets `T212_DEMO_API_KEY`, `T212_DEMO_API_SECRET` and `T212_AGENT_TOKEN`.
3. Protect `/t212/*` with Cloudflare Access/MFA and verify the read routes.
4. Only after Trading 212 confirms the intended customised-interface use is permitted, create D1, apply `migrations/0001_proposals.sql`, copy the binding from `wrangler.execution.example.toml` with the real database ID, and add the separate `T212_APPROVER_TOKEN` secret.
5. Call `/health`; both `credentialsConfigured` and `executionConfigured` must be `true`.
6. Call `/t212/test`, `/t212/instruments`, `/t212/orders` and `/t212/positions` before any write.

Do not paste any key, secret or control token into chat, GitHub, a workbook or a URL.

## Approved Demo smoke test

Create a proposal with the exact T212 ticker and minimal quantity:

```json
{
  "environment": "demo",
  "ticker": "EXACT_T212_TICKER",
  "quantity": 0.01
}
```

The response supplies a unique trade ID. Katie must approve that ID and exact order through the human-only route. The agent route may then submit it once. Verify using the proposal verification route and confirm the same order inside the Trading 212 Practice UI.

Instrument metadata is not a dependable live bid/ask feed. The final price and spread gate remains a current Trading 212 UI check.

## Local test

```bash
npm test
```

The test covers authentication, Demo account read, one market-order submission, duplicate blocking and order read-back without contacting Trading 212.
