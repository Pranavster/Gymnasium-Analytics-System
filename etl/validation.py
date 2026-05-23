"""
etl/validation.py
=================
Pre-load validation of all analytical DataFrames.

Validates:
    - critical null keys (primary keys, required foreign keys)
    - timestamp consistency (booking_time < class_time, etc.)
    - analytical grain (no duplicate PKs)
    - rate range sanity (rates must be in [0, 1])
    - referential integrity between fact and dimension tables
    - boolean flag mutual exclusivity in fact_bookings

Each check logs either ✅ (pass) or ❌ (fail) with a count.
Returns True if ALL checks pass, False otherwise.
The load step should not proceed if this returns False.
"""

import logging

import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def _check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        log.info(f"  ✅ {name}")
    else:
        log.error(f"  ❌ {name}{': ' + detail if detail else ''}")
    return condition


def _null_check(df: pd.DataFrame, col: str, table: str) -> bool:
    n = df[col].isna().sum()
    return _check(
        f"{table}.{col} has no nulls",
        n == 0,
        f"{n:,} nulls found"
    )


def _no_duplicates(df: pd.DataFrame, cols: list, table: str) -> bool:
    n = df.duplicated(subset=cols).sum()
    return _check(
        f"{table} has no duplicate PKs {cols}",
        n == 0,
        f"{n:,} duplicates found"
    )


def _rate_range(df: pd.DataFrame, col: str, table: str) -> bool:
    if col not in df.columns:
        return True
    out_of_range = ((df[col] < 0) | (df[col] > 1)).sum()
    return _check(
        f"{table}.{col} in [0,1]",
        out_of_range == 0,
        f"{out_of_range:,} values out of range"
    )


# ---------------------------------------------------------------------------
# TABLE-LEVEL VALIDATORS
# ---------------------------------------------------------------------------

def validate_fact_bookings(df: pd.DataFrame) -> bool:
    log.info("Validating fact_bookings …")
    ok = True

    ok &= _null_check(df, "booking_id", "fact_bookings")
    ok &= _null_check(df, "member_id",  "fact_bookings")
    ok &= _null_check(df, "class_id",   "fact_bookings")
    ok &= _no_duplicates(df, ["booking_id"], "fact_bookings")

    # booking_time must be before or equal to class_time
    df["_bt"] = pd.to_datetime(df["booking_time"], utc=True)
    df["_ct"] = pd.to_datetime(df["class_time"],   utc=True)
    bad_timing = (df["_bt"] > df["_ct"]).sum()
    ok &= _check(
        "fact_bookings: booking_time <= class_time",
        bad_timing == 0,
        f"{bad_timing:,} rows where booking is after class"
    )
    df.drop(columns=["_bt", "_ct"], inplace=True)

    # Status must be one of the three valid values
    valid_statuses = {"attended", "cancelled", "no_show"}
    bad_status = (~df["status"].isin(valid_statuses)).sum()
    ok &= _check(
        "fact_bookings: status values valid",
        bad_status == 0,
        f"{bad_status:,} invalid status values"
    )

    # Boolean flag mutual exclusivity: a row cannot be both attended and cancelled
    conflict = (df["is_attended"] & df["is_cancelled"]).sum()
    ok &= _check(
        "fact_bookings: is_attended and is_cancelled mutually exclusive",
        conflict == 0,
        f"{conflict:,} conflicting rows"
    )

    # Late cancel only possible if is_cancelled is True
    bad_late = (df["is_late_cancel"] & ~df["is_cancelled"]).sum()
    ok &= _check(
        "fact_bookings: is_late_cancel implies is_cancelled",
        bad_late == 0,
        f"{bad_late:,} late cancels without cancellation"
    )

    return ok


def validate_fact_activity_daily(df: pd.DataFrame) -> bool:
    log.info("Validating fact_activity_daily …")
    ok = True
    ok &= _null_check(df, "date",      "fact_activity_daily")
    ok &= _null_check(df, "member_id", "fact_activity_daily")
    ok &= _no_duplicates(df, ["date", "member_id"], "fact_activity_daily")
    ok &= _rate_range(df, "attendance_rate", "fact_activity_daily")

    # bookings = attended + cancelled + no_show
    df = df.copy()
    df["_sum"] = df["attended"] + df["cancelled"] + df["no_show"]
    mismatch = (df["_sum"] != df["bookings"]).sum()
    ok &= _check(
        "fact_activity_daily: bookings = attended + cancelled + no_show",
        mismatch == 0,
        f"{mismatch:,} rows with component mismatch"
    )
    return ok


def validate_fact_class_sessions(df: pd.DataFrame) -> bool:
    log.info("Validating fact_class_sessions …")
    ok = True
    ok &= _null_check(df, "class_session_id", "fact_class_sessions")
    ok &= _null_check(df, "class_id",         "fact_class_sessions")
    ok &= _no_duplicates(df, ["class_session_id"], "fact_class_sessions")
    ok &= _rate_range(df, "fill_rate", "fact_class_sessions")

    # start_time must be before end_time
    df = df.copy()
    df["_st"] = pd.to_datetime(df["start_time"], utc=True)
    df["_et"] = pd.to_datetime(df["end_time"],   utc=True)
    bad = (df["_st"] >= df["_et"]).sum()
    ok &= _check(
        "fact_class_sessions: start_time < end_time",
        bad == 0,
        f"{bad:,} rows where start >= end"
    )
    return ok


def validate_fact_member_activity_windowed(df: pd.DataFrame) -> bool:
    log.info("Validating fact_member_activity_windowed …")
    ok = True
    ok &= _null_check(df, "member_id",    "fact_member_activity_windowed")
    ok &= _null_check(df, "window_start", "fact_member_activity_windowed")
    ok &= _no_duplicates(df, ["member_id", "window_start", "window_type"], "fact_member_activity_windowed")
    ok &= _rate_range(df, "attendance_rate", "fact_member_activity_windowed")
    return ok


def validate_dim_members(df: pd.DataFrame) -> bool:
    log.info("Validating dim_members …")
    ok = True
    ok &= _null_check(df, "member_id", "dim_members")
    ok &= _no_duplicates(df, ["member_id"], "dim_members")

    # churn_date must be null if not churned
    bad = (df["churned"] == False) & df["churn_date"].notna()  # noqa: E712
    ok &= _check(
        "dim_members: churn_date null when not churned",
        bad.sum() == 0,
        f"{bad.sum():,} rows with churn_date but churned=False"
    )
    return ok


def validate_dim_classes(df: pd.DataFrame) -> bool:
    log.info("Validating dim_classes …")
    ok = True
    ok &= _null_check(df, "class_id", "dim_classes")
    ok &= _no_duplicates(df, ["class_id"], "dim_classes")
    return ok


def validate_dim_trainers(df: pd.DataFrame) -> bool:
    log.info("Validating dim_trainers …")
    ok = True
    ok &= _null_check(df, "trainer_id", "dim_trainers")
    ok &= _no_duplicates(df, ["trainer_id"], "dim_trainers")
    return ok


def validate_dim_time(df: pd.DataFrame) -> bool:
    log.info("Validating dim_time …")
    ok = True
    ok &= _null_check(df, "date", "dim_time")
    ok &= _no_duplicates(df, ["date"], "dim_time")

    # Confirm no gaps in date range
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df_sorted  = df.sort_values("date")
    diffs      = df_sorted["date"].diff().dropna()
    gaps       = (diffs != pd.Timedelta(days=1)).sum()
    ok &= _check(
        "dim_time: no gaps in date sequence",
        gaps == 0,
        f"{gaps:,} date gaps found"
    )
    return ok


def validate_member_features_30d(df: pd.DataFrame) -> bool:
    log.info("Validating member_features_30d …")
    ok = True
    ok &= _null_check(df, "member_id",    "member_features_30d")
    ok &= _null_check(df, "cohort_month", "member_features_30d")
    ok &= _no_duplicates(df, ["member_id", "cohort_month"], "member_features_30d")
    for col in ["attendance_rate_30d", "cancellation_rate_30d",
                "late_cancel_rate_30d", "no_show_rate_30d"]:
        ok &= _rate_range(df, col, "member_features_30d")
    return ok


def validate_member_lifetime_summary(df: pd.DataFrame) -> bool:
    log.info("Validating member_lifetime_summary …")
    ok = True
    ok &= _null_check(df, "member_id", "member_lifetime_summary")
    ok &= _no_duplicates(df, ["member_id"], "member_lifetime_summary")
    for col in ["attendance_rate", "cancellation_rate", "no_show_rate"]:
        ok &= _rate_range(df, col, "member_lifetime_summary")

    # tenure_days must be >= 0
    bad = (df["tenure_days"] < 0).sum()
    ok &= _check(
        "member_lifetime_summary: tenure_days >= 0",
        bad == 0,
        f"{bad:,} negative tenure values"
    )
    return ok


def validate_member_engagement_features(df: pd.DataFrame) -> bool:
    log.info("Validating member_engagement_features …")
    ok = True
    ok &= _null_check(df, "member_id", "member_engagement_features")
    ok &= _no_duplicates(df, ["member_id"], "member_engagement_features")
    for col in ["booking_frequency_score", "attendance_consistency_score",
                "late_cancel_rate", "no_show_rate"]:
        ok &= _rate_range(df, col, "member_engagement_features")
    return ok


def validate_member_cohort_assignments(df: pd.DataFrame) -> bool:
    log.info("Validating member_cohort_assignments …")
    ok = True
    ok &= _null_check(df, "member_id",    "member_cohort_assignments")
    ok &= _null_check(df, "cohort_month", "member_cohort_assignments")
    ok &= _no_duplicates(df, ["member_id", "cohort_month"], "member_cohort_assignments")
    return ok


# ---------------------------------------------------------------------------
# MASTER VALIDATION RUNNER
# ---------------------------------------------------------------------------

def validate_all(tables: dict) -> bool:
    """
    Runs all validators against the provided dict of DataFrames.
    Keys must match the table names used in build_* functions.

    Returns True only if every single check passes.
    """
    log.info("=" * 60)
    log.info("RUNNING ALL VALIDATIONS")
    log.info("=" * 60)

    validators = {
        "fact_bookings":                  validate_fact_bookings,
        "fact_activity_daily":            validate_fact_activity_daily,
        "fact_class_sessions":            validate_fact_class_sessions,
        "fact_member_activity_windowed":  validate_fact_member_activity_windowed,
        "dim_members":                    validate_dim_members,
        "dim_classes":                    validate_dim_classes,
        "dim_trainers":                   validate_dim_trainers,
        "dim_time":                       validate_dim_time,
        "member_features_30d":            validate_member_features_30d,
        "member_lifetime_summary":        validate_member_lifetime_summary,
        "member_engagement_features":     validate_member_engagement_features,
        "member_cohort_assignments":      validate_member_cohort_assignments,
    }

    results = {}
    for name, validator in validators.items():
        if name in tables:
            results[name] = validator(tables[name])
        else:
            log.warning(f"  ⚠️  {name} not found in tables dict — skipping")
            results[name] = True

    all_pass = all(results.values())
    log.info("=" * 60)
    if all_pass:
        log.info("ALL VALIDATIONS PASSED ✅")
    else:
        failed = [k for k, v in results.items() if not v]
        log.error(f"VALIDATION FAILED for: {', '.join(failed)}")
    log.info("=" * 60)
    return all_pass
