"""Streamlit admin dashboard — Mission Control for the follow-up system.

Run with:
    streamlit run dashboard.py --server.port 8501

Reads directly from the SQLite database (read-only). No API calls needed.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

from database import SessionLocal

st.set_page_config(page_title="Follow-up Mission Control", layout="wide")
st.title("Follow-up System — Mission Control")


def get_db():
    return SessionLocal()


# --- Tab Layout ---
tab1, tab2, tab3 = st.tabs(["Queue Management", "System Logs", "Error Monitor"])


# --- Tab 1: Queue Management ---
with tab1:
    st.header("Pending Follow-ups")
    db = get_db()
    try:
        query = text("""
            SELECT
                st.id AS task_id,
                l.email,
                st.task_type,
                st.scheduled_time,
                l.campaign_status,
                l.follow_up_count
            FROM scheduled_tasks st
            JOIN leads l ON st.lead_id = l.id
            WHERE st.status = 'pending'
            ORDER BY st.scheduled_time ASC
        """)
        result = db.execute(query)
        rows = result.fetchall()

        if rows:
            df = pd.DataFrame(rows, columns=["Task ID", "Email", "Task Type",
                                               "Scheduled Time", "Status", "Follow-ups Sent"])
            now = datetime.now(timezone.utc)
            df["Scheduled Time"] = pd.to_datetime(df["Scheduled Time"])
            df["Days Until Send"] = df["Scheduled Time"].apply(
                lambda t: max(0, (t - now).days) if pd.notna(t) else "?"
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.metric("Total Pending", len(rows))
        else:
            st.info("No pending follow-ups in the queue.")
    finally:
        db.close()


# --- Tab 2: System Logs ---
with tab2:
    st.header("Recent Activity")

    col1, col2 = st.columns(2)
    with col1:
        action_filter = st.text_input("Filter by action", placeholder="e.g. email_sent")
    with col2:
        email_filter = st.text_input("Filter by email", placeholder="e.g. john@example.com")

    db = get_db()
    try:
        base_query = """
            SELECT
                sl.timestamp,
                sl.action,
                sl.level,
                COALESCE(l.email, '-') AS email,
                sl.details
            FROM system_logs sl
            LEFT JOIN leads l ON sl.lead_id = l.id
            WHERE 1=1
        """
        params = {}

        if action_filter:
            base_query += " AND sl.action LIKE :action"
            params["action"] = f"%{action_filter}%"
        if email_filter:
            base_query += " AND l.email LIKE :email"
            params["email"] = f"%{email_filter}%"

        base_query += " ORDER BY sl.timestamp DESC LIMIT 100"

        result = db.execute(text(base_query), params)
        rows = result.fetchall()

        if rows:
            df = pd.DataFrame(rows, columns=["Timestamp", "Action", "Level", "Email", "Details"])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No log entries found.")
    finally:
        db.close()


# --- Tab 3: Error Monitor ---
with tab3:
    st.header("Error Monitor")

    db = get_db()
    try:
        now = datetime.now(timezone.utc)

        # Error counts by time window
        windows = {
            "Last 24 hours": now - timedelta(hours=24),
            "Last 7 days": now - timedelta(days=7),
            "Last 30 days": now - timedelta(days=30),
        }

        cols = st.columns(len(windows))
        for i, (label, since) in enumerate(windows.items()):
            result = db.execute(
                text("SELECT COUNT(*) FROM system_logs WHERE level = 'error' AND timestamp >= :since"),
                {"since": since.isoformat()},
            )
            count = result.scalar()
            cols[i].metric(label, count)

        # Error details grouped by action
        st.subheader("Recent Errors")
        result = db.execute(text("""
            SELECT
                sl.timestamp,
                sl.action,
                COALESCE(l.email, '-') AS email,
                sl.details
            FROM system_logs sl
            LEFT JOIN leads l ON sl.lead_id = l.id
            WHERE sl.level = 'error'
            ORDER BY sl.timestamp DESC
            LIMIT 50
        """))
        rows = result.fetchall()

        if rows:
            df = pd.DataFrame(rows, columns=["Timestamp", "Action", "Email", "Details"])

            # Group summary
            if not df.empty:
                summary = df.groupby("Action").size().reset_index(name="Count").sort_values("Count", ascending=False)
                st.dataframe(summary, use_container_width=True, hide_index=True)

            # Expandable detail rows
            st.subheader("Error Details")
            for _, row in df.iterrows():
                with st.expander(f"{row['Timestamp']} — {row['Action']} ({row['Email']})"):
                    st.text(row["Details"] or "No details")
        else:
            st.success("No errors recorded.")
    finally:
        db.close()
