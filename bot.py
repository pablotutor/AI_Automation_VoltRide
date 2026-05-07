#!/usr/bin/env python3
"""
VoltRide Thread C — Automatic QC anomaly detection bot
Combines RPA (conformance checking, file I/O, alerting) with LLM (diagnosis, report drafting)
"""

import os
import sys
import csv
import json
from dotenv import load_dotenv
load_dotenv()
import smtplib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from ollama import Client as OllamaClient

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

LOG_DIR = Path("logs")
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")

LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Environment variables
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")

GMAIL_SENDER = os.getenv("GMAIL_SENDER", "voltride.bot@example.com")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
GMAIL_RECIPIENT = os.getenv("GMAIL_RECIPIENT", "supervisor@voltride.example.com")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Use the post-disruption log as the operational event source
EVENT_LOG_PATH = DATA_DIR / "voltride_event_log_POST.csv"
AUDIT_LOG_PATH = OUTPUT_DIR / f"audit_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
DASHBOARD_PATH = OUTPUT_DIR / "qc_dashboard.csv"

# SOP-QC-002: QC Incoming must occur before Production Started.
# During the supply-chain disruption, some orders bypassed incoming component
# inspection and went directly to production, creating quality and traceability risk.
CONFORMANCE_RULE = "QC Incoming"
CONFORMANCE_GATE = "Production Started"  # rule activity must precede this gate

# For a historical log set this high enough to cover the full window you want to audit.
# With the POST log (starting 2026-04-20), 720 h covers ~30 days.
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "24"))
ALERT_THRESHOLD_RATE = 0.15  # 15%

# ═══════════════════════════════════════════════════════════════
# RPA LAYER — Deterministic operations
# ═══════════════════════════════════════════════════════════════

def load_event_log(path: Path) -> List[Dict[str, Any]]:
    """RPA: Load and parse CSV event log"""
    logger.info(f"Loading event log from {path}")
    if not path.exists():
        logger.error(f"Event log not found at {path}")
        raise FileNotFoundError(f"Event log at {path}")

    events = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append(row)

    logger.info(f"Loaded {len(events)} events from {len(set(r['case_id'] for r in events))} orders")
    return events


def filter_recent_orders(events: List[Dict], hours: int = LOOKBACK_HOURS) -> Dict[str, List[Dict]]:
    """RPA: Filter orders with any activity in the last N hours, grouped by order ID"""
    logger.info(f"Filtering orders with activity in last {hours} hours")
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)

    orders: Dict[str, List[Dict]] = {}
    for event in events:
        order_id = event['case_id']
        try:
            ts = datetime.strptime(event['timestamp'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.warning(f"Skipping event with unparseable timestamp: {event['timestamp']}")
            continue

        if cutoff <= ts <= now:
            if order_id not in orders:
                orders[order_id] = []
            orders[order_id].append(event)

    logger.info(f"Found {len(orders)} orders in lookback window")
    return orders


def conformance_check(order_events: List[Dict]) -> Dict[str, Any]:
    """
    RPA: Conformance check — SOP-QC-002.
    Rule: 'QC Incoming' must appear before 'Production Started'.
    Non-conforming if Production Started occurs without a prior QC Incoming.
    """
    activities = [e['activity'] for e in order_events]

    has_rule = CONFORMANCE_RULE in activities
    has_gate = CONFORMANCE_GATE in activities

    if not has_gate:
        # Order never reached production — no violation possible
        conforms = True
    elif has_gate and not has_rule:
        conforms = False
    else:
        rule_idx = activities.index(CONFORMANCE_RULE)
        gate_idx = activities.index(CONFORMANCE_GATE)
        conforms = rule_idx < gate_idx

    return {
        'conforms': conforms,
        'activity_sequence': activities,
        'has_qc_incoming': has_rule,
        'has_production_started': has_gate,
    }

# ═══════════════════════════════════════════════════════════════
# LLM LAYER — Intelligent diagnosis and drafting
# ═══════════════════════════════════════════════════════════════

def generate_diagnosis(client: OllamaClient, order_id: str, order_events: List[Dict], check_result: Dict) -> Dict[str, Any]:
    """
    LLM: Generate causal diagnosis and draft report for non-conforming order.
    Returns structured JSON with diagnosis, risk level, and mini-report.
    """
    first = order_events[0]
    customer_type = first.get('customer_type', 'N/A')
    priority = first.get('priority', 'N/A')
    supplier = first.get('supplier', 'N/A')
    activities = check_result['activity_sequence']

    prompt = f"""You are a supply-chain QC supervisor at VoltRide.
VoltRide recently suffered a supply-chain disruption. As an emergency measure, some orders
bypassed the standard incoming component inspection (SOP-QC-002), going directly from
Credit Check to Production Started without "QC Incoming" or component receipt confirmation.

A production order has violated SOP-QC-002.

Order ID: {order_id}
Customer type: {customer_type}
Priority: {priority}
Supplier: {supplier}
Activity sequence: {' → '.join(activities)}

Your task:
1. Identify which mandatory step was skipped.
2. Suggest the likely cause given the disruption context.
3. Assess the risk level (low/medium/high) — consider that unverified components could cause field defects.
4. Draft a one-paragraph mini-report for the operations supervisor.

Respond ONLY with valid JSON (no markdown, no preamble):
{{
  "activity_gap": "which step was skipped",
  "likely_cause": "your analysis of why this happened given the disruption context",
  "risk_level": "low|medium|high",
  "mini_report": "One paragraph explaining the issue, the quality risk, and recommended action."
}}
"""

    logger.info(f"Calling Ollama API for order {order_id} (model: {OLLAMA_MODEL})")

    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": 800},
    )

    response_text = response.message.content.strip()
    logger.debug(f"Raw LLM response: {response_text}")

    try:
        diagnosis = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        diagnosis = {
            "activity_gap": "QC Incoming not found before Production Started",
            "likely_cause": "Emergency bypass during supply-chain disruption",
            "risk_level": "medium",
            "mini_report": (
                f"Order {order_id} (supplier: {supplier}) did not pass incoming component "
                f"inspection before production. This may indicate an emergency stock bypass. "
                f"Manual traceability check required."
            )
        }

    diagnosis['order_id'] = order_id
    diagnosis['customer_type'] = customer_type
    diagnosis['priority'] = priority
    diagnosis['supplier'] = supplier
    diagnosis['timestamp'] = datetime.now().isoformat()

    return diagnosis

# ═══════════════════════════════════════════════════════════════
# OUTPUT LAYER — Multi-channel alerting
# ═══════════════════════════════════════════════════════════════

def send_email(subject: str, body: str, recipient: str = GMAIL_RECIPIENT) -> bool:
    """RPA: Send email via Gmail SMTP"""
    if not GMAIL_PASSWORD:
        logger.warning("Gmail credentials not configured, skipping email")
        return False

    try:
        logger.info(f"Sending email to {recipient}")
        msg = MIMEMultipart()
        msg['From'] = GMAIL_SENDER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_SENDER, GMAIL_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_telegram(message: str, chat_id: str = TELEGRAM_CHAT_ID) -> bool:
    """RPA: Send alert via Telegram Bot API"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured, skipping notification")
        return False

    try:
        logger.info(f"Sending Telegram message to chat {chat_id}")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            logger.info("Telegram message sent successfully")
            return True
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def write_audit_log(entry: Dict[str, Any]) -> None:
    """RPA: Write structured audit log entry (JSONL format)"""
    entry['logged_at'] = datetime.now().isoformat()
    with open(AUDIT_LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')
    logger.debug(f"Audit log entry written: {entry['order_id']}")


def update_dashboard(diagnoses: List[Dict]) -> None:
    """RPA: Write QC dashboard CSV with all detected anomalies"""
    logger.info(f"Writing dashboard with {len(diagnoses)} anomalies")

    with open(DASHBOARD_PATH, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['timestamp', 'order_id', 'customer_type', 'priority', 'supplier', 'risk_level', 'likely_cause']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for diag in diagnoses:
            writer.writerow({
                'timestamp': diag['timestamp'],
                'order_id': diag['order_id'],
                'customer_type': diag.get('customer_type', 'N/A'),
                'priority': diag.get('priority', 'N/A'),
                'supplier': diag.get('supplier', 'N/A'),
                'risk_level': diag.get('risk_level', 'unknown'),
                'likely_cause': diag.get('likely_cause', 'N/A'),
            })

# ═══════════════════════════════════════════════════════════════
# MAIN ORCHESTRATION
# ═══════════════════════════════════════════════════════════════

def run_bot(event_log_path: Path = EVENT_LOG_PATH) -> Dict[str, Any]:
    """Main bot execution orchestrating RPA + LLM pipeline"""
    logger.info("=" * 70)
    logger.info("VoltRide Thread C Bot — START")
    logger.info(f"Conformance rule: {CONFORMANCE_RULE} must precede {CONFORMANCE_GATE}")
    logger.info(f"Lookback window: {LOOKBACK_HOURS} hours")
    logger.info("=" * 70)

    client = OllamaClient(
        host=OLLAMA_BASE_URL,
        headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
    )

    # Phase 1: RPA — Load and filter
    events = load_event_log(event_log_path)
    orders = filter_recent_orders(events, hours=LOOKBACK_HOURS)

    # Phase 2: RPA — Conformance checking
    non_conforming_orders = {}
    conforming_count = 0
    for order_id, order_events in orders.items():
        check = conformance_check(order_events)
        if check['conforms']:
            conforming_count += 1
        else:
            non_conforming_orders[order_id] = {'events': order_events, 'check': check}

    nc_rate = len(non_conforming_orders) / len(orders) if orders else 0
    logger.info(
        f"Conformance check: {len(non_conforming_orders)} non-conforming / {len(orders)} orders "
        f"({nc_rate*100:.1f}%)"
    )

    # Phase 3: LLM — Diagnosis for each non-conforming order
    diagnoses = []
    for order_id, order_data in non_conforming_orders.items():
        diagnosis = generate_diagnosis(client, order_id, order_data['events'], order_data['check'])
        diagnoses.append(diagnosis)
        write_audit_log({'stage': 'llm_diagnosis', 'order_id': order_id, 'llm_output': diagnosis, 'status': 'diagnosed'})

    # Phase 4: RPA — Multi-channel output
    if diagnoses:
        report_subject = f"VoltRide QC Anomalies (SOP-QC-002) — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        report_body = (
            f"QC Non-Conformance Report — SOP-QC-002 (QC Incoming before Production)\n\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Orders checked (last {LOOKBACK_HOURS}h): {len(orders)}\n"
            f"Non-conforming: {len(diagnoses)} ({nc_rate*100:.1f}%)\n\n"
            + "=" * 70 + "\n\n"
        )

        for diagnosis in diagnoses:
            report_body += (
                f"Order:         {diagnosis['order_id']}\n"
                f"Customer type: {diagnosis.get('customer_type', 'N/A')}\n"
                f"Priority:      {diagnosis.get('priority', 'N/A')}\n"
                f"Supplier:      {diagnosis.get('supplier', 'N/A')}\n"
                f"Risk Level:    {diagnosis.get('risk_level', 'unknown')}\n"
                f"Likely Cause:  {diagnosis.get('likely_cause', 'N/A')}\n\n"
                f"Report:\n{diagnosis.get('mini_report', 'N/A')}\n\n"
                + "-" * 70 + "\n\n"
            )

        email_sent = send_email(report_subject, report_body)

        for diagnosis in diagnoses:
            send_telegram(
                f"<b>QC Anomaly — SOP-QC-002 Violation</b>\n"
                f"Order: {diagnosis['order_id']}\n"
                f"Supplier: {diagnosis.get('supplier', '?')}\n"
                f"Priority: {diagnosis.get('priority', '?')}\n"
                f"Risk: {diagnosis.get('risk_level', '?').upper()}\n"
                f"Cause: {diagnosis.get('likely_cause', 'Unknown')}"
            )

        for diagnosis in diagnoses:
            write_audit_log({
                'stage': 'output',
                'order_id': diagnosis['order_id'],
                'channels': ['email' if email_sent else 'none', 'telegram'],
                'status': 'sent',
            })

    # Phase 5: Alert if overall rate exceeds threshold
    if nc_rate > ALERT_THRESHOLD_RATE:
        send_telegram(
            f"<b>ALERT: High QC Non-conformance Rate</b>\n"
            f"{nc_rate*100:.1f}% of orders skipped QC Incoming "
            f"(threshold: {ALERT_THRESHOLD_RATE*100:.0f}%)\nImmediate investigation required."
        )
        logger.warning(f"ALERT: Non-conformance rate {nc_rate*100:.1f}% exceeds threshold")

    # Phase 6: RPA — Update dashboard
    update_dashboard(diagnoses)
    write_audit_log({
        'stage': 'run_summary',
        'order_id': '__summary__',
        'total_orders_checked': len(orders),
        'non_conforming': len(diagnoses),
        'nc_rate_pct': round(nc_rate * 100, 1),
    })

    logger.info("=" * 70)
    logger.info("VoltRide Thread C Bot — COMPLETE")
    logger.info(f"Non-conforming orders detected: {len(diagnoses)}")
    logger.info(f"Audit log: {AUDIT_LOG_PATH}")
    logger.info(f"Dashboard: {DASHBOARD_PATH}")
    logger.info("=" * 70)

    return {
        'timestamp': datetime.now().isoformat(),
        'total_orders_checked': len(orders),
        'non_conforming': len(diagnoses),
        'nc_rate_pct': round(nc_rate * 100, 1),
        'diagnoses': diagnoses,
        'audit_log': str(AUDIT_LOG_PATH),
        'dashboard': str(DASHBOARD_PATH),
    }


if __name__ == "__main__":
    try:
        result = run_bot()
        print("\n" + json.dumps(result, indent=2))
        sys.exit(0)
    except Exception as e:
        logger.error(f"Bot execution failed: {e}", exc_info=True)
        sys.exit(1)
