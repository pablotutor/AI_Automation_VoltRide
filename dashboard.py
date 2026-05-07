#!/usr/bin/env python3
"""
VoltRide QC Dashboard — live view of bot output
Run with: streamlit run dashboard.py
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ── Config ──────────────────────────────────────────────────────────────────
DASHBOARD_CSV = Path("output/qc_dashboard.csv")
AUDIT_LOG_DIR = Path("output")
ALERT_THRESHOLD = 0.15
REFRESH_MS = 30_000  # 30 seconds

st.set_page_config(
    page_title="VoltRide QC Monitor",
    page_icon="⚡",
    layout="wide",
)

st_autorefresh(interval=REFRESH_MS, key="autorefresh")

# ── Header ───────────────────────────────────────────────────────────────────
st.title("⚡ VoltRide — QC Non-Conformance Monitor")
st.caption("SOP-QC-002 · QC Incoming must precede Production Started · Auto-refresh every 30s")

# ── Load data ────────────────────────────────────────────────────────────────
if not DASHBOARD_CSV.exists():
    st.info("No bot runs detected yet. Run `python bot.py` to start.")
    st.stop()

df = pd.read_csv(DASHBOARD_CSV, parse_dates=["timestamp"])
last_run = datetime.fromtimestamp(DASHBOARD_CSV.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

# ── Metrics ───────────────────────────────────────────────────────────────────
nc_count = len(df)

# Estimate total orders from the audit log (last run summary) — fall back to nc_count
total_orders = nc_count
audit_files = sorted(AUDIT_LOG_DIR.glob("audit_log_*.jsonl"), reverse=True)
if audit_files:
    try:
        with open(audit_files[0]) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        output_entries = [e for e in entries if e.get("stage") == "output"]
        if output_entries:
            total_orders = max(total_orders, len(output_entries))
    except Exception:
        pass

nc_rate = nc_count / total_orders if total_orders else 0
alert = nc_rate > ALERT_THRESHOLD

col1, col2, col3, col4 = st.columns(4)
col1.metric("Orders (non-conforming)", nc_count)
col2.metric("NC Rate", f"{nc_rate*100:.1f}%")
col3.metric("Threshold", f"{ALERT_THRESHOLD*100:.0f}%")
col4.metric("Status", "ALERT" if alert else "OK", delta="above threshold" if alert else "within threshold",
            delta_color="inverse")

if alert:
    st.error(f"Non-conformance rate {nc_rate*100:.1f}% exceeds the {ALERT_THRESHOLD*100:.0f}% threshold — immediate investigation required.")
else:
    st.success(f"Non-conformance rate within acceptable range.")

st.divider()

# ── Risk distribution ─────────────────────────────────────────────────────────
col_chart, col_table = st.columns([1, 2])

with col_chart:
    st.subheader("Risk Distribution")
    risk_counts = df["risk_level"].str.lower().value_counts().reindex(
        ["high", "medium", "low"], fill_value=0
    ).rename(index=str.capitalize)
    st.bar_chart(risk_counts, color=["#e74c3c"])

# ── Anomaly table ─────────────────────────────────────────────────────────────
with col_table:
    st.subheader("Detected Anomalies")
    st.dataframe(
        df[["timestamp", "order_id", "supplier", "customer_type", "priority", "risk_level", "likely_cause"]],
        use_container_width=True,
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Detected", format="YYYY-MM-DD HH:mm"),
            "order_id": "Order",
            "supplier": "Supplier",
            "customer_type": "Type",
            "priority": "Priority",
            "risk_level": "Risk",
            "likely_cause": st.column_config.TextColumn("Likely Cause", width="large"),
        },
        hide_index=True,
    )

st.divider()

# ── Audit log viewer ──────────────────────────────────────────────────────────
st.subheader("LLM Diagnosis Log")

if not audit_files:
    st.info("No audit log found.")
else:
    with open(audit_files[0]) as f:
        entries = [json.loads(l) for l in f if l.strip()]

    diag_entries = [e for e in entries if e.get("stage") == "llm_diagnosis"][-20:]

    for entry in reversed(diag_entries):
        out = entry.get("llm_output", {})
        risk = out.get("risk_level", "?").upper()
        risk_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(risk, "⚪")
        label = f"{risk_icon} {entry['order_id']} · {out.get('supplier', '')} · Risk: {risk}"

        with st.expander(label):
            st.markdown(f"**Activity gap:** {out.get('activity_gap', 'N/A')}")
            st.markdown(f"**Likely cause:** {out.get('likely_cause', 'N/A')}")
            st.info(out.get("mini_report", "No report available."))
            st.caption(f"Diagnosed at: {entry.get('logged_at', 'N/A')}")

# ── Footer ────────────────────────────────────────────────────────────────────
st.caption(f"Last bot run: {last_run} · Dashboard auto-refreshes every 30s")
