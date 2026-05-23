"""
etl/transform_bookings.py
=========================
Transforms raw operational booking/attendance/cancellation data into
four analytics fact tables.

Grain summary
-------------
fact_bookings                 : one row per booking event
fact_activity_daily           : one row per (member, date)
fact_class_sessions           : one row per scheduled class session
fact_member_activity_windowed : one row per (member, rolling window start)

All inputs are plain pandas DataFrames produced by extract.extract_all().
No database reads occur here.
"""

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# A cancellation is "late" if it occurred less than 24 hours before class_time
LATE_CANCEL_HOURS = 24

# Rolling window sizes (days) for fact_member_activity_windowed
ACTIVITY_WINDOWS = [7, 30, 90]


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def _safe_rate(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """
    Computes numerator / denominator, returning 0.00 wherever denominator
    is zero or NaN rather than inf or NaN.  Result rounded to 2 dp.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        rate = np.where(denominator > 0, numerator / denominator, 0.0)
    return pd.Series(rate, index=numerator.index).round(2)


# ---------------------------------------------------------------------------
# 1. FACT BOOKINGS
# ---------------------------------------------------------------------------

def build_fact_bookings(
    bookings:      pd.DataFrame,
    attendance:    pd.DataFrame,
    cancellations: pd.DataFrame,
    schedules:     pd.DataFrame,
) -> pd.DataFrame:
    """
    Grain: one row per booking.

    Joins bookings → schedules (for class_id, trainer_id, class_time)
                   → attendance (for attended / no_show status)
                   → cancellations (for cancelled status + timing)

    Derived status (mutually exclusive, exhaustive):
        attended   — booking exists, attendance.status = 'attended'
        cancelled  — cancellation row exists for this booking
        no_show    — booking exists, no cancellation, attendance.status = 'no_show'
                     OR booking exists, no cancellation, no attendance row

    Late cancellation definition:
        cancellation_time < class_time  AND
        (class_time - cancellation_time) < 24 hours
    """
    log.info("Building fact_bookings …")

    # --- Normalise column types ---
    bookings      = bookings.copy()
    schedules     = schedules.copy()
    attendance    = attendance.copy()
    cancellations = cancellations.copy()

    # Ensure timestamps are timezone-aware (coerce if needed)
    for df, col in [
        (bookings,      "booked_at"),
        (schedules,     "scheduled_at"),
        (cancellations, "cancelled_at"),
    ]:
        df[col] = pd.to_datetime(df[col], utc=True)

    # --- Base: every booking ---
    fact = bookings[["booking_id", "member_id", "schedule_id", "booked_at"]].copy()
    fact.rename(columns={"booked_at": "booking_time"}, inplace=True)

    # --- Add class_id, trainer_id, class_time from schedules ---
    sched_cols = schedules[["schedule_id", "class_id", "trainer_id", "scheduled_at"]].copy()
    sched_cols.rename(columns={"scheduled_at": "class_time"}, inplace=True)
    fact = fact.merge(sched_cols, on="schedule_id", how="left")

    # --- Add cancellation info ---
    cancel_cols = cancellations[
        ["booking_id", "cancelled_at", "cancellation_type"]
    ].copy()
    cancel_cols.rename(columns={"cancelled_at": "cancellation_time"}, inplace=True)
    fact = fact.merge(cancel_cols, on="booking_id", how="left")

    # --- Add attendance status ---
    attend_cols = attendance[["booking_id", "status"]].copy()
    attend_cols.rename(columns={"status": "attend_status"}, inplace=True)
    fact = fact.merge(attend_cols, on="booking_id", how="left")

    # --- Derive boolean flags ---
    fact["is_cancelled"] = fact["cancellation_time"].notna()

    # Late cancel: cancellation exists AND it was within 24 h of class start
    time_to_class = (fact["class_time"] - fact["cancellation_time"]).dt.total_seconds() / 3600
    fact["is_late_cancel"] = fact["is_cancelled"] & (time_to_class < LATE_CANCEL_HOURS)

    # attended: not cancelled AND attendance row says 'attended'
    fact["is_attended"] = (~fact["is_cancelled"]) & (fact["attend_status"] == "attended")

    # no_show: not cancelled AND (attendance = 'no_show' OR no attendance row at all)
    fact["is_no_show"] = (~fact["is_cancelled"]) & (fact["attend_status"] != "attended")

    # --- Derive unified status column ---
    conditions = [
        fact["is_cancelled"],
        fact["is_attended"],
        fact["is_no_show"],
    ]
    choices = ["cancelled", "attended", "no_show"]
    fact["status"] = np.select(conditions, choices, default="unknown")

    # --- Final column selection matching DDL ---
    result = fact[[
        "booking_id",
        "member_id",
        "class_id",
        "trainer_id",
        "booking_time",
        "class_time",
        "status",
        "cancellation_time",
        "is_cancelled",
        "is_late_cancel",
        "is_no_show",
        "is_attended",
    ]].copy()

    log.info(f"  fact_bookings: {len(result):,} rows")
    log.info(f"    attended={result['is_attended'].sum():,}  "
             f"cancelled={result['is_cancelled'].sum():,}  "
             f"no_show={result['is_no_show'].sum():,}")
    return result


# ---------------------------------------------------------------------------
# 2. FACT ACTIVITY DAILY
# ---------------------------------------------------------------------------

def build_fact_activity_daily(fact_bookings: pd.DataFrame) -> pd.DataFrame:
    """
    Grain: one row per (member_id, date).

    Derived from fact_bookings, not raw OLTP tables, so all status
    definitions are already standardised.

    date is the DATE portion of booking_time (when the member made the
    booking), not the class date — this captures booking behaviour per day.
    """
    log.info("Building fact_activity_daily …")

    df = fact_bookings.copy()
    df["date"] = pd.to_datetime(df["booking_time"]).dt.date

    grp = df.groupby(["date", "member_id"])

    daily = pd.DataFrame({
        "bookings":  grp["booking_id"].count(),
        "attended":  grp["is_attended"].sum(),
        "cancelled": grp["is_cancelled"].sum(),
        "no_show":   grp["is_no_show"].sum(),
    }).reset_index()

    daily["attendance_rate"] = _safe_rate(daily["attended"], daily["bookings"])

    # Cast to correct types
    for col in ["bookings", "attended", "cancelled", "no_show"]:
        daily[col] = daily[col].astype(int)

    log.info(f"  fact_activity_daily: {len(daily):,} rows")
    return daily


# ---------------------------------------------------------------------------
# 3. FACT CLASS SESSIONS
# ---------------------------------------------------------------------------

def build_fact_class_sessions(
    schedules:  pd.DataFrame,
    classes:    pd.DataFrame,
    fact_bookings: pd.DataFrame,
) -> pd.DataFrame:
    """
    Grain: one row per scheduled class session (schedule_id).

    attended_count = number of fact_booking rows with is_attended=True
                     for that schedule_id.
    fill_rate      = attended_count / session capacity  (capped at 1.00)

    class_session_id = schedule_id (same grain, direct mapping).
    """
    log.info("Building fact_class_sessions …")

    # Attended headcount per session
    attended_per_session = (
        fact_bookings[fact_bookings["is_attended"]]
        .groupby("class_id")   # NOTE: we group by schedule via the fact table
        .size()
        .reset_index(name="attended_count_tmp")
    )

    # We need per-schedule attendance, not per-class
    attended_per_sched = (
        fact_bookings[fact_bookings["is_attended"]]
        .groupby("booking_id")  # booking_id is unique; we need schedule grain
        .size()
    )

    # Correct approach: count attended bookings per (schedule implied by class_time)
    # fact_bookings has no schedule_id directly — join back via schedules
    # Actually fact_bookings DOES keep class_id/trainer_id but not schedule_id.
    # We need to re-join to schedules to get schedule_id.
    # Re-merge fact_bookings with schedules on (class_id, trainer_id, class_time).

    sched = schedules[["schedule_id", "class_id", "trainer_id",
                        "scheduled_at", "capacity"]].copy()
    sched["scheduled_at"] = pd.to_datetime(sched["scheduled_at"], utc=True)
    sched.rename(columns={"scheduled_at": "class_time"}, inplace=True)

    fb = fact_bookings[["class_id", "trainer_id", "class_time", "is_attended"]].copy()

    # Merge fact_bookings back to schedule_id
    fb_sched = fb.merge(
        sched[["schedule_id", "class_id", "trainer_id", "class_time", "capacity"]],
        on=["class_id", "trainer_id", "class_time"],
        how="left",
    )

    attended_per_sched = (
        fb_sched[fb_sched["is_attended"]]
        .groupby("schedule_id")["is_attended"]
        .sum()
        .reset_index()
        .rename(columns={"is_attended": "attended_count"})
    )

    # Base: all schedules
    sessions = sched.merge(attended_per_sched, on="schedule_id", how="left")
    sessions["attended_count"] = sessions["attended_count"].fillna(0).astype(int)

    # end_time = start_time + duration_minutes from classes
    class_duration = classes[["class_id", "duration_minutes"]].copy()
    sessions = sessions.merge(class_duration, on="class_id", how="left")

    sessions["end_time"] = (
        sessions["class_time"]
        + pd.to_timedelta(sessions["duration_minutes"].fillna(60), unit="m")
    )

    sessions["fill_rate"] = _safe_rate(
        sessions["attended_count"].astype(float),
        sessions["capacity"].astype(float),
    ).clip(upper=1.00)

    result = sessions[[
        "schedule_id",
        "class_id",
        "trainer_id",
        "class_time",
        "end_time",
        "capacity",
        "attended_count",
        "fill_rate",
    ]].copy()
    result.rename(columns={
        "schedule_id": "class_session_id",
        "class_time":  "start_time",
    }, inplace=True)

    log.info(f"  fact_class_sessions: {len(result):,} rows | "
             f"avg fill rate: {result['fill_rate'].mean():.2%}")
    return result


# ---------------------------------------------------------------------------
# 4. FACT MEMBER ACTIVITY WINDOWED
# ---------------------------------------------------------------------------

def build_fact_member_activity_windowed(
    fact_bookings: pd.DataFrame,
    members: pd.DataFrame,
    window_days: int = 30,
    window_type: str = "30d",
) -> pd.DataFrame:
    """
    Grain: one row per (member_id, window_start).

    For each member, creates non-overlapping windows of `window_days` days
    starting from their signup date through their last booking.

    window_type label matches the DDL TEXT column — call this function
    multiple times with different window_days/window_type values if you
    want 7d, 30d, and 90d windows all in one table.
    """
    log.info(f"Building fact_member_activity_windowed ({window_type}) …")

    members = members.copy()
    members["join_date"] = pd.to_datetime(members["join_date"], utc=True)

    fb = fact_bookings.copy()
    fb["booking_date"] = pd.to_datetime(fb["booking_time"]).dt.tz_convert("UTC")

    rows = []

    for _, member in members.iterrows():
        mid       = member["member_id"]
        start     = member["join_date"]
        mb        = fb[fb["member_id"] == mid]

        if mb.empty:
            continue

        last_booking = mb["booking_date"].max()
        window_start = start

        while window_start <= last_booking:
            window_end = window_start + pd.Timedelta(days=window_days)
            mask       = (mb["booking_date"] >= window_start) & (mb["booking_date"] < window_end)
            window_df  = mb[mask]

            total = len(window_df)
            if total == 0:
                window_start = window_end
                continue

            attended  = int(window_df["is_attended"].sum())
            cancelled = int(window_df["is_cancelled"].sum())
            no_show   = int(window_df["is_no_show"].sum())
            att_rate  = round(attended / total, 2) if total > 0 else 0.00

            rows.append({
                "member_id":       mid,
                "window_start":    window_start.date(),
                "window_end":      window_end.date(),
                "window_type":     window_type,
                "bookings":        total,
                "attended":        attended,
                "cancelled":       cancelled,
                "no_show":         no_show,
                "attendance_rate": att_rate,
            })
            window_start = window_end

    result = pd.DataFrame(rows)
    log.info(f"  fact_member_activity_windowed ({window_type}): {len(result):,} rows")
    return result
