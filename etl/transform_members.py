"""
etl/transform_members.py
========================
Transforms operational member/trainer/class data into dimension tables
and member-level analytical/feature tables.

Depends on:
    - raw operational DataFrames (from extract.extract_all)
    - fact_bookings DataFrame (from transform_bookings.build_fact_bookings)

No database reads occur here.

Churn definition used throughout:
    A member is considered churned if they have not made any booking
    in the last 60 days AND their is_active flag is False.
    churn_date is set to the date of their last booking + 60 days.
"""

import logging
from datetime import date, timedelta

import pandas as pd
import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# Days of inactivity after which a member is considered churned
CHURN_INACTIVITY_DAYS = 60

# Feature score normalisation: booking frequency is scored per 30-day window
BOOKING_FREQ_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def _safe_rate(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        rate = np.where(denominator > 0, numerator / denominator, 0.0)
    return pd.Series(rate, index=numerator.index).round(2)


def _churn_flag(row, last_booking_map: dict, today: date) -> tuple[bool, date | None]:
    """
    Returns (churned: bool, churn_date: date | None).

    Logic:
        If is_active is False AND last booking is more than
        CHURN_INACTIVITY_DAYS ago → churned=True, churn_date = last_booking + 60d.
        Otherwise → churned=False, churn_date=None.
    """
    mid          = row["member_id"]
    is_active    = row["is_active"]
    last_booking = last_booking_map.get(mid)

    if not is_active and last_booking is not None:
        days_since = (today - last_booking).days
        if days_since >= CHURN_INACTIVITY_DAYS:
            return True, last_booking + timedelta(days=CHURN_INACTIVITY_DAYS)

    return False, None


# ---------------------------------------------------------------------------
# 1. DIM MEMBERS
# ---------------------------------------------------------------------------

def build_dim_members(
    members: pd.DataFrame,
    fact_bookings: pd.DataFrame,
) -> pd.DataFrame:
    """
    Grain: one row per member.

    Churn is derived from is_active + recency of last booking.
    signup = join_date cast to timestamptz.
    """
    log.info("Building dim_members …")

    today = date.today()

    # Last booking date per member
    fb = fact_bookings.copy()
    fb["booking_date"] = pd.to_datetime(fb["booking_time"]).dt.date
    last_booking_map = fb.groupby("member_id")["booking_date"].max().to_dict()

    result_rows = []
    for _, row in members.iterrows():
        churned, churn_date = _churn_flag(row, last_booking_map, today)
        result_rows.append({
            "member_id":       row["member_id"],
            "signup":          pd.to_datetime(row["join_date"], utc=True),
            "churned":         churned,
            "churn_date":      pd.to_datetime(churn_date, utc=True) if churn_date else None,
            "membership_type": row["membership_tier"],
        })

    result = pd.DataFrame(result_rows)
    churned_count = result["churned"].sum()
    log.info(f"  dim_members: {len(result):,} rows | churned: {churned_count}")
    return result


# ---------------------------------------------------------------------------
# 2. DIM CLASSES
# ---------------------------------------------------------------------------

def build_dim_classes(classes: pd.DataFrame) -> pd.DataFrame:
    """
    Grain: one row per class.
    Direct projection from operational classes table.
    """
    log.info("Building dim_classes …")
    result = classes[["class_id", "class_type", "capacity", "duration_minutes"]].copy()
    log.info(f"  dim_classes: {len(result):,} rows")
    return result


# ---------------------------------------------------------------------------
# 3. DIM TRAINERS
# ---------------------------------------------------------------------------

def build_dim_trainers(trainers: pd.DataFrame) -> pd.DataFrame:
    """
    Grain: one row per trainer.
    hire_date cast to timestamptz. specialty → specialization per DDL.
    """
    log.info("Building dim_trainers …")
    result = trainers[["trainer_id", "hire_date", "specialty"]].copy()
    result["hire_date"] = pd.to_datetime(result["hire_date"], utc=True)
    result.rename(columns={"specialty": "specialization"}, inplace=True)
    log.info(f"  dim_trainers: {len(result):,} rows")
    return result


# ---------------------------------------------------------------------------
# 4. DIM TIME
# ---------------------------------------------------------------------------

def build_dim_time(fact_bookings: pd.DataFrame, schedules: pd.DataFrame) -> pd.DataFrame:
    """
    Grain: one row per calendar date.

    Covers every date that appears in either booking_time or scheduled_at
    so that all fact tables can join to this dimension without gaps.
    """
    log.info("Building dim_time …")

    booking_dates  = pd.to_datetime(fact_bookings["booking_time"]).dt.date
    schedule_dates = pd.to_datetime(schedules["scheduled_at"], utc=True).dt.date

    all_dates = pd.Series(
        pd.date_range(
            start=min(booking_dates.min(), schedule_dates.min()),
            end=max(booking_dates.max(), schedule_dates.max()),
            freq="D",
        ).date
    )

    result = pd.DataFrame({"date": all_dates})
    dt = pd.to_datetime(result["date"])
    result["day_of_week"]  = dt.dt.dayofweek          # 0=Monday … 6=Sunday
    result["week_of_year"] = dt.dt.isocalendar().week.astype(int)
    result["month"]        = dt.dt.month
    result["quarter"]      = dt.dt.quarter
    result["is_weekend"]   = dt.dt.dayofweek >= 5

    log.info(f"  dim_time: {len(result):,} rows")
    return result


# ---------------------------------------------------------------------------
# 5. MEMBER FEATURES 30D
# ---------------------------------------------------------------------------

def build_member_features_30d(
    members: pd.DataFrame,
    fact_bookings: pd.DataFrame,
) -> pd.DataFrame:
    """
    Grain: one row per (member_id, cohort_month).

    Analyses each member's behaviour in the FIRST 30 DAYS after their
    signup date.  cohort_month is the first day of the member's signup month.

    avg_booking_lead_time:
        Mean of (class_time - booking_time) for bookings made in this window.
        Stored as an INTERVAL — represented here as a Python timedelta and
        inserted as a PostgreSQL interval string.
    """
    log.info("Building member_features_30d …")

    members = members.copy()
    members["join_date"] = pd.to_datetime(members["join_date"], utc=True)

    fb = fact_bookings.copy()
    fb["booking_time"] = pd.to_datetime(fb["booking_time"], utc=True)
    fb["class_time"]   = pd.to_datetime(fb["class_time"],   utc=True)
    fb["lead_seconds"] = (fb["class_time"] - fb["booking_time"]).dt.total_seconds()

    rows = []

    for _, member in members.iterrows():
        mid       = member["member_id"]
        join_dt   = member["join_date"]
        window_end = join_dt + pd.Timedelta(days=30)

        # Cohort month = first day of signup month
        cohort_month = join_dt.date().replace(day=1)

        mb = fb[
            (fb["member_id"] == mid) &
            (fb["booking_time"] >= join_dt) &
            (fb["booking_time"] <  window_end)
        ]

        total     = len(mb)
        attended  = int(mb["is_attended"].sum())
        cancelled = int(mb["is_cancelled"].sum())
        late_cancel = int(mb["is_late_cancel"].sum())
        no_show   = int(mb["is_no_show"].sum())

        att_rate        = round(attended  / total, 2) if total > 0 else 0.00
        cancel_rate     = round(cancelled / total, 2) if total > 0 else 0.00
        late_cancel_rate = round(late_cancel / total, 2) if total > 0 else 0.00
        no_show_rate    = round(no_show   / total, 2) if total > 0 else 0.00

        # avg_booking_lead_time as a timedelta (will be cast to interval on insert)
        valid_leads = mb["lead_seconds"].dropna()
        if not valid_leads.empty:
            avg_lead = pd.to_timedelta(valid_leads.mean(), unit="s")
        else:
            avg_lead = None

        rows.append({
            "member_id":              mid,
            "cohort_month":           cohort_month,
            "booking_count_30d":      total,
            "attendance_rate_30d":    att_rate,
            "cancellation_rate_30d":  cancel_rate,
            "late_cancel_rate_30d":   late_cancel_rate,
            "no_show_rate_30d":       no_show_rate,
            "avg_booking_lead_time":  avg_lead,
        })

    result = pd.DataFrame(rows)
    log.info(f"  member_features_30d: {len(result):,} rows")
    return result


# ---------------------------------------------------------------------------
# 6. MEMBER LIFETIME SUMMARY
# ---------------------------------------------------------------------------

def build_member_lifetime_summary(
    members: pd.DataFrame,
    fact_bookings: pd.DataFrame,
) -> pd.DataFrame:
    """
    Grain: one row per member.

    Aggregates lifetime booking/attendance/cancellation metrics.
    Churn logic mirrors dim_members for consistency.
    tenure_days = today - signup_date.
    """
    log.info("Building member_lifetime_summary …")

    today = date.today()

    members = members.copy()
    members["join_date"] = pd.to_datetime(members["join_date"], utc=True)

    fb = fact_bookings.copy()
    fb["booking_date"] = pd.to_datetime(fb["booking_time"]).dt.date

    # Aggregate per member
    agg = fb.groupby("member_id").agg(
        total_bookings=("booking_id",   "count"),
        total_attended=("is_attended",  "sum"),
        total_cancelled=("is_cancelled","sum"),
        total_no_show= ("is_no_show",   "sum"),
        last_booking_date=("booking_date", "max"),
    ).reset_index()

    # Merge with member base info
    result = members[["member_id", "join_date", "is_active"]].merge(
        agg, on="member_id", how="left"
    )

    # Fill members with zero bookings
    for col in ["total_bookings", "total_attended", "total_cancelled", "total_no_show"]:
        result[col] = result[col].fillna(0).astype(int)

    last_booking_map = dict(zip(agg["member_id"], agg["last_booking_date"]))

    # Churn flags
    churned_flags  = []
    churn_dates    = []
    for _, row in result.iterrows():
        churned, churn_date = _churn_flag(row, last_booking_map, today)
        churned_flags.append(churned)
        churn_dates.append(pd.to_datetime(churn_date, utc=True) if churn_date else None)

    result["churned"]    = churned_flags
    result["churn_date"] = churn_dates

    # Tenure
    result["tenure_days"] = (
        pd.to_datetime(today) - result["join_date"].dt.tz_localize(None)
    ).dt.days.astype(int)

    # Rates
    result["attendance_rate"]   = _safe_rate(result["total_attended"],  result["total_bookings"])
    result["cancellation_rate"] = _safe_rate(result["total_cancelled"], result["total_bookings"])
    result["no_show_rate"]      = _safe_rate(result["total_no_show"],   result["total_bookings"])

    result.rename(columns={"join_date": "signup_date"}, inplace=True)

    final = result[[
        "member_id",
        "signup_date",
        "churned",
        "churn_date",
        "tenure_days",
        "total_bookings",
        "total_attended",
        "attendance_rate",
        "cancellation_rate",
        "no_show_rate",
        "last_booking_date",
    ]].copy()

    log.info(f"  member_lifetime_summary: {len(final):,} rows")
    return final


# ---------------------------------------------------------------------------
# 7. MEMBER ENGAGEMENT FEATURES
# ---------------------------------------------------------------------------

def build_member_engagement_features(
    member_lifetime_summary: pd.DataFrame,
    fact_bookings: pd.DataFrame,
    members: pd.DataFrame,
) -> pd.DataFrame:
    """
    Grain: one row per member.

    Produces normalised, reusable feature components ONLY.
    The final weighted engagement KPI is intentionally NOT computed here —
    this table is a feature store for downstream scoring / ML use.

    booking_frequency_score:
        bookings per 30 days of tenure, min-max normalised to [0, 1]
        across all members.

    attendance_consistency_score:
        attendance_rate from lifetime summary — already in [0, 1].

    late_cancel_rate and no_show_rate:
        taken directly from lifetime summary (already normalised rates).
    """
    log.info("Building member_engagement_features …")

    fb = fact_bookings.copy()
    members = members.copy()
    members["join_date"] = pd.to_datetime(members["join_date"])

    # booking_frequency_score: bookings / (tenure_days / 30)
    summary = member_lifetime_summary[[
        "member_id", "tenure_days", "total_bookings",
        "attendance_rate", "cancellation_rate", "no_show_rate",
    ]].copy()

    # Late cancel rate requires fact_bookings since lifetime_summary doesn't store it
    late_cancel_agg = (
        fb.groupby("member_id")
        .apply(lambda g: g["is_late_cancel"].sum() / max(len(g), 1))
        .reset_index()
        .rename(columns={0: "late_cancel_rate"})
    )

    summary = summary.merge(late_cancel_agg, on="member_id", how="left")
    summary["late_cancel_rate"] = summary["late_cancel_rate"].fillna(0.0).round(2)

    # Raw booking frequency (bookings per 30-day period)
    summary["tenure_periods"] = summary["tenure_days"].clip(lower=1) / 30
    summary["raw_freq"]       = summary["total_bookings"] / summary["tenure_periods"]

    # Min-max normalise to [0, 1]
    freq_min = summary["raw_freq"].min()
    freq_max = summary["raw_freq"].max()
    if freq_max > freq_min:
        summary["booking_frequency_score"] = (
            (summary["raw_freq"] - freq_min) / (freq_max - freq_min)
        ).round(2)
    else:
        summary["booking_frequency_score"] = 0.0

    result = summary[[
        "member_id",
        "booking_frequency_score",
        "attendance_rate",          # attendance_consistency_score
        "late_cancel_rate",
        "no_show_rate",
    ]].copy()
    result.rename(columns={"attendance_rate": "attendance_consistency_score"}, inplace=True)

    log.info(f"  member_engagement_features: {len(result):,} rows")
    return result


# ---------------------------------------------------------------------------
# 8. MEMBER COHORT ASSIGNMENTS
# ---------------------------------------------------------------------------

def build_member_cohort_assignments(members: pd.DataFrame) -> pd.DataFrame:
    """
    Grain: one row per (member_id, cohort_month).

    cohort_month = first day of the month in which the member signed up.

    Currently produces exactly one row per member (one cohort per member).
    The PRIMARY KEY(member_id, cohort_month) supports future expansion
    where a member might be assigned to multiple analytical cohorts.
    """
    log.info("Building member_cohort_assignments …")

    members = members.copy()
    members["join_date"] = pd.to_datetime(members["join_date"], utc=True)

    result = pd.DataFrame({
        "member_id":   members["member_id"],
        "cohort_month": members["join_date"].dt.to_period("M").dt.to_timestamp().dt.date,
        "signup_date": members["join_date"],
    })

    log.info(f"  member_cohort_assignments: {len(result):,} rows | "
             f"cohorts: {result['cohort_month'].nunique()}")
    return result
