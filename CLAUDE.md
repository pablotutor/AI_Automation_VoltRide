# CLAUDE.md — VoltRide QC Bot

## What this project is

VoltRide Thread C is a QC anomaly detection bot for UAM Business Analytics (Topic 6, May 2026).
It detects production orders that skip mandatory QC inspection, diagnoses the root cause via LLM,
and alerts supervisors through Gmail and Telegram.

Stack: Python 3.10+, Ollama Cloud (`gpt-oss:120b`), OpenAI-compatible API.

## Project layout

```
bot.py                     # Main bot — entry point
data/
  voltride_event_log.csv          # Pre-disruption log (T5, sessions 1-2)
  voltride_event_log_POST.csv     # Post-disruption log — bot default input
docs/
  EXECUTION_PLAN.md        # Class demo timeline and checklist
output/                    # Generated at runtime — gitignored
logs/                      # Generated at runtime — gitignored
requirements.txt
.env.example               # Copy to .env and fill in credentials
```

## Running the bot

```bash
cp .env.example .env        # fill in OLLAMA_API_KEY at minimum
pip install -r requirements.txt
python bot.py
```

## Architecture

The bot has three layers:
- **RPA layer** — deterministic: CSV parsing, conformance check (SOP-QA-001), file I/O, email/Telegram dispatch
- **LLM layer** — semantic: Ollama `gpt-oss:120b` diagnoses *why* an order skipped QC, returns structured JSON
- **Audit layer** — every LLM call is logged to `output/audit_log_*.jsonl` with prompt + output + timestamp

## Key constants (bot.py top)

| Variable | Default | Purpose |
|---|---|---|
| `LOOKBACK_HOURS` | 720 (30 days) | Window for filtering recent orders; override via env var |
| `ALERT_THRESHOLD_RATE` | 0.15 | Triggers extra Telegram alert if NC rate > 15% |
| `OLLAMA_MODEL` | `gpt-oss:120b` | Override via `OLLAMA_MODEL` env var |
| `OLLAMA_BASE_URL` | `https://api.ollama.com/v1` | Override for local Ollama or other endpoints |
| `CONFORMANCE_RULE` | `QC Incoming` | Step that must precede `Production Started` |

## LLM integration

Uses the `openai` Python SDK pointing at Ollama's OpenAI-compatible endpoint.
The client is initialized in `run_bot()` and passed down to `generate_diagnosis()`.
Response must be valid JSON — fallback diagnosis is applied on parse failure.

## What NOT to commit

- `.env` (real credentials) — already in `.gitignore`
- `logs/` and `output/` (runtime artifacts) — already in `.gitignore`

## Deadline

13 May 2026 23:59 — UAM Moodle submission.
