# Oracle ↔ Evonic setup

Wires the **Oracle** advisory market-stance engine (Bun/TS) into Evonic as
declarative agents + a thin tool-bridge skill. The agents reuse Evonic's loop,
LLM routing, `chat.db`, and scheduler — no agent code lives in Evonic.

## 1. Deploy the Oracle engine (on the server)

```bash
cd /root && git clone git@github.com:renakaagusta/oracle.git   # → /root/oracle
cd /root/oracle && bun install
cp .env.example .env    # fill in:
#   ORACLE_SCRAPER_SECRET   (shared stackbase gateway)
#   ORACLE_SWARMSCOPE_URL / ORACLE_SWARMSCOPE_KEY   (oracle-* namespace key)
#   ORACLE_LLM_*  — optional; the LLM judgment runs in Evonic, not the CLI
bun test    # sanity
```

The skill bridge calls `bun run src/cli.ts` with `cwd=/root/oracle`. Override
paths via env if needed: `ORACLE_DIR` (default `/root/oracle`), `ORACLE_BUN`
(default `bun`; set to the mise path if `bun` isn't on PATH for the Evonic
process).

## 2. Swarmscope namespaces

Add to swarmscope's `LEDGER_API_KEYS` and merge swarmscope PR #1:

```
oracle-crypto:<key>,oracle-ihsg:<key>,oracle-us:<key>,oracle-commodity:<key>
```

Point `ORACLE_SWARMSCOPE_KEY` at one of these.

## 3. Register the agents (Evonic API, on the server)

The skill (`skills/oracle/`) is auto-discovered. The SYSTEM.md prompts ship in
`agents/oracle_*/SYSTEM.md`. Create the agent rows + grant the skill + schedule:

```bash
API=http://127.0.0.1:5000   # Evonic API base

for A in oracle_analyst oracle_scorekeeper oracle_scribe; do
  curl -s -X POST $API/api/agents -H 'content-type: application/json' \
    -d "{\"id\":\"$A\",\"name\":\"$A\",\"enabled\":true,\"system_prompt\":\"$(sed 's/"/\\"/g' agents/$A/SYSTEM.md | tr '\n' ' ')\"}"
done

# Grant the oracle skill's tools to each agent (Analyst gets data+publish; the
# others get only what they need):
curl -s -X PUT $API/api/agents/oracle_analyst/skills    -d '{"skills":["oracle"]}' -H 'content-type: application/json'
curl -s -X PUT $API/api/agents/oracle_scorekeeper/skills -d '{"skills":["oracle"]}' -H 'content-type: application/json'
curl -s -X PUT $API/api/agents/oracle_scribe/skills      -d '{"skills":["oracle"]}' -H 'content-type: application/json'
```

(Optionally restrict tools per agent via `PUT /api/agents/<id>/tools` —
Analyst: `oracle_candidates`,`oracle_publish_stance`,`oracle_tick_plan`;
Scorekeeper: `oracle_grade_due`; Scribe: `oracle_daily_brief`,`oracle_weekly_review`,`oracle_tuning`.)

## 4. Schedules (cadence + 24×7 catalyst watch)

Use the Evonic scheduler (`schedules` table / scheduler API). Suggested:

| Agent | Trigger | Notes |
|---|---|---|
| `oracle_analyst` (crypto) | cron hourly | 24×7 |
| `oracle_analyst` (US, IHSG) | cron every 90m **and** an off-hours catalyst tick | use `oracle_tick_plan` to gate; futures/FX proxies cover closed sessions |
| `oracle_analyst` (commodity) | cron 2×/day | |
| `oracle_scorekeeper` | cron hourly | grades matured stances |
| `oracle_scribe` | cron daily + weekly | brief + accuracy review |

Each schedule's action injects a tick message (e.g. "assess CRYPTO now") into the
agent's session. The Analyst itself calls `oracle_tick_plan` if it needs to
confirm a class is due / detect an off-session event trigger.

## Guarantees

- **No execution path**: the skill exposes only read/advisory tools; the Oracle
  CLI has no trade command (enforced in `oracle/src/safety.ts`).
- **Bounded context**: agents act on the small candidate cards, one symbol at a
  time — no raw OHLCV in the transcript.
