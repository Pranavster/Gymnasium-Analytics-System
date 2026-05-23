"""
etl/load.py
===========
Loads all validated analytical DataFrames into the PostgreSQL analytics schema.

Design decisions:
    - Each load_* function truncates its target table before inserting.
      This makes the pipeline fully idempotent: re-running it always produces
      a clean, consistent analytics layer derived from the current OLTP state.

    - Inserts use psycopg2 execute_values for batch performance.

    - avg_booking_lead_time (a pandas Timedelta) is converted to a
      PostgreSQL interval string before insert.

    - All functions accept a live psycopg2 connection; the caller
      (run.py) owns the connection lifecycle.

    - Schema is configurable but defaults to "gym_analytics" which is
      where both OLTP and analytics tables live in this project.
      If you later move analytics tables to a separate schema, change
      ANALYTICS_SCHEMA below.
"""

import logging

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

log = logging.getLogger(__name__)

ANALYTICS_SCHEMA = "gym_analytics"


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def _truncate(cur, table: str) -> None:
    cur.execute(f'TRUNCATE TABLE {ANALYTICS_SCHEMA}."{table}" RESTART IDENTITY CASCADE')


def _timedelta_to_pg_interval(td) -> str | None:
    """Convert a pandas Timedelta (or None/NaT) to a PostgreSQL interval string."""
    if td is None or pd.isna(td):
        return None
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(abs(total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    sign = "-" if total_seconds < 0 else ""
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}"


def _load(conn, table: str, rows: list, sql: str, label: str) -> None:
    """Generic truncate-then-batch-insert."""
    with conn.cursor() as cur:
        _truncate(cur, table)
        execute_values(cur, sql, rows)
    conn.commit()
    log.info(f"  Loaded {label}: {len(rows):,} rows → {ANALYTICS_SCHEMA}.{table}")


# ---------------------------------------------------------------------------
# FACT TABLES
# ---------------------------------------------------------------------------

def load_fact_bookings(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.booking_id,
            row.member_id,
            row.class_id,
            row.trainer_id,
            row.booking_time,
            row.class_time,
            row.status,
            row.cancellation_time if not pd.isna(row.cancellation_time) else None,
            bool(row.is_cancelled),
            bool(row.is_late_cancel),
            bool(row.is_no_show),
            bool(row.is_attended),
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.fact_bookings
        (booking_id, member_id, class_id, trainer_id,
         booking_time, class_time, status, cancellation_time,
         is_cancelled, is_late_cancel, is_no_show, is_attended)
        VALUES %s
    """
    _load(conn, "fact_bookings", rows, sql, "fact_bookings")


def load_fact_activity_daily(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.date,
            row.member_id,
            int(row.bookings),
            int(row.attended),
            int(row.cancelled),
            int(row.no_show),
            float(row.attendance_rate),
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.fact_activity_daily
        (date, member_id, bookings, attended, cancelled, no_show, attendance_rate)
        VALUES %s
    """
    _load(conn, "fact_activity_daily", rows, sql, "fact_activity_daily")


def load_fact_class_sessions(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.class_session_id,
            row.class_id,
            row.trainer_id,
            row.start_time,
            row.end_time,
            int(row.capacity),
            int(row.attended_count),
            float(row.fill_rate),
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.fact_class_sessions
        (class_session_id, class_id, trainer_id,
         start_time, end_time, capacity, attended_count, fill_rate)
        VALUES %s
    """
    _load(conn, "fact_class_sessions", rows, sql, "fact_class_sessions")


def load_fact_member_activity_windowed(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.member_id,
            row.window_start,
            row.window_end,
            row.window_type,
            int(row.bookings),
            int(row.attended),
            int(row.cancelled),
            int(row.no_show),
            float(row.attendance_rate),
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.fact_member_activity_windowed
        (member_id, window_start, window_end, window_type,
         bookings, attended, cancelled, no_show, attendance_rate)
        VALUES %s
    """
    _load(conn, "fact_member_activity_windowed", rows, sql, "fact_member_activity_windowed")


# ---------------------------------------------------------------------------
# DIMENSION TABLES
# ---------------------------------------------------------------------------

def load_dim_members(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.member_id,
            row.signup,
            bool(row.churned),
            row.churn_date if not pd.isna(row.churn_date) else None,
            row.membership_type,
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.dim_members
        (member_id, signup, churned, churn_date, membership_type)
        VALUES %s
    """
    _load(conn, "dim_members", rows, sql, "dim_members")


def load_dim_classes(conn, df: pd.DataFrame) -> None:
    rows = [
        (row.class_id, row.class_type, int(row.capacity), int(row.duration_minutes))
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.dim_classes
        (class_id, class_type, capacity, duration_minutes)
        VALUES %s
    """
    _load(conn, "dim_classes", rows, sql, "dim_classes")


def load_dim_trainers(conn, df: pd.DataFrame) -> None:
    rows = [
        (row.trainer_id, row.hire_date, row.specialization)
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.dim_trainers
        (trainer_id, hire_date, specialization)
        VALUES %s
    """
    _load(conn, "dim_trainers", rows, sql, "dim_trainers")


def load_dim_time(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.date,
            int(row.day_of_week),
            int(row.week_of_year),
            int(row.month),
            int(row.quarter),
            bool(row.is_weekend),
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.dim_time
        (date_pk, day_of_week, week_of_year, month, quarter, is_weekend)
        VALUES %s
    """
    _load(conn, "dim_time", rows, sql, "dim_time")


# ---------------------------------------------------------------------------
# FEATURE / ANALYTICAL TABLES
# ---------------------------------------------------------------------------

def load_member_features_30d(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.member_id,
            row.cohort_month,
            int(row.booking_count_30d),
            float(row.attendance_rate_30d),
            float(row.cancellation_rate_30d),
            float(row.late_cancel_rate_30d),
            float(row.no_show_rate_30d),
            _timedelta_to_pg_interval(row.avg_booking_lead_time),
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.member_features_30d
        (member_id, cohort_month, booking_count_30d,
         attendance_rate_30d, cancellation_rate_30d,
         late_cancel_rate_30d, no_show_rate_30d, avg_booking_lead_time)
        VALUES %s
    """
    _load(conn, "member_features_30d", rows, sql, "member_features_30d")


def load_member_lifetime_summary(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.member_id,
            row.signup_date,
            bool(row.churned),
            row.churn_date if not pd.isna(row.churn_date) else None,
            int(row.tenure_days),
            int(row.total_bookings),
            int(row.total_attended),
            float(row.attendance_rate),
            float(row.cancellation_rate),
            float(row.no_show_rate),
            row.last_booking_date if not pd.isna(row.last_booking_date) else None,
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.member_lifetime_summary
        (member_id, signup_date, churned, churn_date, tenure_days,
         total_bookings, total_attended, attendance_rate,
         cancellation_rate, no_show_rate, last_booking_date)
        VALUES %s
    """
    _load(conn, "member_lifetime_summary", rows, sql, "member_lifetime_summary")


def load_member_engagement_features(conn, df: pd.DataFrame) -> None:
    rows = [
        (
            row.member_id,
            float(row.booking_frequency_score),
            float(row.attendance_consistency_score),
            float(row.late_cancel_rate),
            float(row.no_show_rate),
        )
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.member_engagement_features
        (member_id, booking_frequency_score, attendance_consistency_score,
         late_cancel_rate, no_show_rate)
        VALUES %s
    """
    _load(conn, "member_engagement_features", rows, sql, "member_engagement_features")


def load_member_cohort_assignments(conn, df: pd.DataFrame) -> None:
    rows = [
        (row.member_id, row.cohort_month, row.signup_date)
        for row in df.itertuples(index=False)
    ]
    sql = f"""
        INSERT INTO {ANALYTICS_SCHEMA}.member_cohort_assignments
        (member_id, cohort_month, signup_date)
        VALUES %s
    """
    _load(conn, "member_cohort_assignments", rows, sql, "member_cohort_assignments")


# ---------------------------------------------------------------------------
# MASTER LOAD RUNNER
# ---------------------------------------------------------------------------

def load_all(conn, tables: dict) -> None:
    """
    Loads all analytical tables in the correct dependency order:
        1. Dimensions first (no dependencies)
        2. Facts second (reference dimensions)
        3. Feature/aggregate tables last (derived from facts)
    """
    log.info("Loading analytics tables …")

    # 1. Dimensions
    load_dim_members(conn,  tables["dim_members"])
    load_dim_classes(conn,  tables["dim_classes"])
    load_dim_trainers(conn, tables["dim_trainers"])
    load_dim_time(conn,     tables["dim_time"])

    # 2. Facts
    load_fact_bookings(conn,                 tables["fact_bookings"])
    load_fact_activity_daily(conn,           tables["fact_activity_daily"])
    load_fact_class_sessions(conn,           tables["fact_class_sessions"])
    load_fact_member_activity_windowed(conn, tables["fact_member_activity_windowed"])

    # 3. Feature / aggregate tables
    load_member_features_30d(conn,          tables["member_features_30d"])
    load_member_lifetime_summary(conn,      tables["member_lifetime_summary"])
    load_member_engagement_features(conn,   tables["member_engagement_features"])
    load_member_cohort_assignments(conn,    tables["member_cohort_assignments"])

    log.info("All analytics tables loaded ✅")
