# VoltRide Thread C — QC Anomaly Detection Bot

**Intelligent automation combining RPA + LLM to detect production orders that skip QC inspection**

## Project Overview

This bot implements **Thread C** of the "Operation Red Yarn" case (UAM Business Analytics, Topic 6). It addresses a critical operational issue: 11.3% of production orders are closed without going through mandatory QC inspection (SOP-QA-001 violation).

The bot:
1. **Loads** the production event log (CSV) every N hours
2. **Detects** orders that skip "QC Finished Goods" before "Delivered"
3. **Diagnoses** the cause using an LLM — grounded in the disruption context (structured JSON output)
4. **Alerts** supervisors via **Gmail** (formal, auditable) and **Telegram** (immediate, real-time)
5. **Logs** all decisions for auditability (GDPR, EU AI Act compliance)
6. **Updates** a live QC dashboard showing compliance rate and risk levels

## Architecture

```
Event Log (CSV)
    ↓ [RPA: Load & parse]
Orders in last 24h
    ↓ [RPA: Deterministic conformance check]
Non-conforming orders
    ↓ [LLM: Ollama gpt-oss:120b diagnosis + causal analysis]
Structured diagnosis (JSON)
    ↓ [RPA: Multi-channel output]
┌──────────────────┬──────────────────┐
Gmail (formal)  Telegram (alerts)  Dashboard (CSV)
└──────────────────┴──────────────────┘
    ↓ [RPA: Structured audit log]
JSONL Audit Log (timestamps, prompts, outputs, actions)
```

**Design principle** — Human / RPA / LLM split:
- **Human**: Supervisor makes final decisions after reading the report
- **RPA**: All deterministic ops (file I/O, conformance rules, alerting)
- **LLM**: Semantic understanding (why did it happen? what is the risk?)

## Setup

### 1. Prerequisites

- Python 3.10+
- Ollama Cloud account (for `gpt-oss:120b`)
- Gmail account (optional, for formal reports)
- Telegram bot (optional, for real-time alerts)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required
OLLAMA_API_KEY=your-ollama-api-key
OLLAMA_BASE_URL=https://api.ollama.com/v1   # default, change if self-hosting
OLLAMA_MODEL=gpt-oss:120b                   # default

# Optional — Gmail formal reports
GMAIL_SENDER=voltride-bot@gmail.com
GMAIL_PASSWORD=your-app-password            # use Gmail App Password, not your real password
GMAIL_RECIPIENT=supervisor@voltride.example.com

# Optional — Telegram real-time alerts
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

### 4. Telegram Bot Setup

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`, follow the prompts, copy the token
3. Add the bot to a group; send any message; then run:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
4. Copy the `"id"` from the `"chat"` object → set as `TELEGRAM_CHAT_ID`

### 5. Gmail Setup

1. Enable 2-step verification on your Gmail account
2. Go to Google Account → Security → App Passwords
3. Generate a 16-character App Password and set it as `GMAIL_PASSWORD`

## Running the Bot

```bash
python bot.py
```

The bot loads `.env` automatically via `python-dotenv` — no need to export variables manually.

### Override lookback window

```bash
LOOKBACK_HOURS=48 python bot.py   # check last 48 hours
LOOKBACK_HOURS=720 python bot.py  # audit last 30 days
```

### Scheduled execution (cron)

```bash
# Every 30 minutes
*/30 * * * * cd /path/to/voltride-bot && python bot.py >> logs/cron.log 2>&1
```

## Streamlit Dashboard

Run in a separate terminal while the bot is running (or after any bot run):

```bash
streamlit run dashboard.py
```

Opens at `http://localhost:8501`. The dashboard auto-refreshes every 30 seconds and shows:
- NC rate metrics and ALERT/OK status (threshold: 15%)
- Risk distribution chart (High / Medium / Low)
- Anomaly table with supplier, customer type, priority, and likely cause
- Expandable LLM diagnosis log with full mini-reports

## Output Artifacts

| Artifact | Path | Description |
|---|---|---|
| Audit log | `output/audit_log_YYYYMMDD_HHMMSS.jsonl` | Every LLM call logged (prompt → output → action) |
| Dashboard | `output/qc_dashboard.csv` | Non-conforming orders, risk levels, causes |
| Bot log | `logs/bot_YYYYMMDD_HHMMSS.log` | Execution trace |

### Example audit log entry

```json
{"stage": "llm_diagnosis", "order_id": "ORD-2026-0074", "llm_output": {"activity_gap": "QC skipped", "likely_cause": "Rush order bypassed inspection", "risk_level": "medium", "mini_report": "..."}, "status": "diagnosed", "logged_at": "2026-05-03T14:22:15.123456"}
```

## Data

Both files share the same schema:

| Column | Description |
|---|---|
| `case_id` | Order ID |
| `activity` | Process step |
| `timestamp` | `YYYY-MM-DD HH:MM:SS` |
| `resource` | Role that executed the step |
| `customer_type` | B2B / B2C |
| `priority` | standard / urgent |
| `quantity` | Units ordered |
| `supplier` | Component supplier |

| File | Period | Orders | Notes |
|---|---|---|---|
| `voltride_event_log.csv` | Oct–Nov 2025 | 420 | Pre-disruption baseline (T5) |
| `voltride_event_log_POST.csv` | Apr–Nov 2026 | 380 | **Bot default** — post-disruption audit |

**Conformance rule (SOP-QC-002)**: `QC Incoming` must appear before `Production Started`.
During the disruption, 78 of 333 completed orders (23.4%) bypassed incoming component inspection.

## Human-in-the-Loop Design

The bot does NOT take irreversible actions:

- **Does**: detect, diagnose, alert, log
- **Does NOT**: close orders, adjust schedules, make production decisions

The supervisor always reviews the diagnosis and decides the corrective action.

## Risk & Compliance

### Hallucination mitigation
- LLM used only for diagnosis (semantic), not for irreversible actions
- Every LLM output logged with prompt and timestamp
- Structured JSON output reduces free-form hallucinations
- Supervisor reviews before acting

### GDPR
- Event log contains no PII (only order IDs and role titles)
- All processing logged for transparency (Article 22)

### EU AI Act
- Classification: **Limited risk** (Article 6d) — classifying process anomalies, not high-risk decisions
- Transparency: all decisions logged, supervisor sees reasoning
- Human oversight: supervisor approves any corrective action

## Testing

```bash
# Test email channel
python -c "from bot import send_email; send_email('Test', 'Test body')"

# Test Telegram channel
python -c "from bot import send_telegram; send_telegram('Test from VoltRide bot')"

# Full end-to-end dry run
python bot.py
```

## Project Structure

```
.
├── bot.py                     # Main bot
├── requirements.txt
├── .env.example               # Credential template
├── CLAUDE.md                  # Claude Code context
├── data/
│   ├── voltride_event_log.csv          # Pre-disruption (T5 baseline)
│   └── voltride_event_log_POST.csv     # Post-disruption (bot default)
├── docs/
│   └── EXECUTION_PLAN.md      # Class demo timeline
├── logs/                      # Created at runtime
└── output/                    # Created at runtime
```

## References

- Topic 5 — Process Mining analysis of VoltRide event log (11.3% anomaly rate)
- Topic 6 — Hyperautomation framework: RPA + LLM + human-in-the-loop
- GDPR Article 22 — automated decision-making transparency
- EU AI Act — limited risk classification and transparency requirements
- SOP-QA-001 — VoltRide internal quality standard

## Author

Developed May 2026 — UAM Business Analytics, MIST Module, Topic 6 Exam.
Submission deadline: 13 May 2026, 23:59.
