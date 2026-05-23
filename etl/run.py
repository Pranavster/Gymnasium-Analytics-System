"""
etl/run.py
==========
Orchestrator for the gym analytics ETL pipeline.

Wires together:
    extract   → pulls raw OLTP tables from PostgreSQL
    transform → builds all analytical DataFrames
    validate  → checks every table before touching the DB
    load      → truncates and reloads all analytics tables

Run modes:
    python run.py            → full pipeline (transform + validate + load)
    python run.py --dry-run  → transform + validate only, no DB writes

The pipeline is fully idempotent: every run truncates analytics tables
and repopulates them from the current OLTP state.  Safe to re-run at any
time without manual cleanup.
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# LOGGING SETUP  (must happen before any module-level logger calls)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LOCAL IMPORTS
# ---------------------------------------------------------------------------

from extract import extract_all, get_connection                         # noqa: E402
from transform_bookings import (                                         # noqa: E402
    build_fact_bookings,
    build_fact_activity_daily,
    build_fact_class_sessions,
    build_fact_member_activity_windowed,
)
from transform_members import (                                          # noqa: E402
    build_dim_members,
    build_dim_classes,
    build_dim_trainers,
    build_dim_time,
    build_member_features_30d,
    build_member_lifetime_summary,
    build_member_engagement_features,
    build_member_cohort_assignments,
)
from validation import validate_all                                      # noqa: E402
from load import load_all                                                # noqa: E402


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> None:
    log.info("=" * 60)
    log.info("Gym Analytics ETL Pipeline")
    log.info(f"  Mode: {'DRY RUN (no DB writes)' if dry_run else 'FULL RUN'}")
    log.info("=" * 60)

    # ------------------------------------------------------------------
    # STEP 1: EXTRACT
    # ------------------------------------------------------------------
    log.info("")
    log.info("STEP 1 — EXTRACT")
    raw = extract_all()

    members      = raw["members"]
    trainers     = raw["trainers"]
    classes      = raw["classes"]
    schedules    = raw["schedules"]
    bookings     = raw["bookings"]
    cancellations = raw["cancellations"]
    attendance   = raw["attendance"]

    # ------------------------------------------------------------------
    # STEP 2: TRANSFORM — Facts
    # ------------------------------------------------------------------
    log.info("")
    log.info("STEP 2 — TRANSFORM: FACTS")

    fact_bookings = build_fact_bookings(
        bookings, attendance, cancellations, schedules
    )
    fact_activity_daily = build_fact_activity_daily(fact_bookings)

    fact_class_sessions = build_fact_class_sessions(
        schedules, classes, fact_bookings
    )

    # Build windowed activity for all three standard windows; combine into one table
    import pandas as pd
    windowed_frames = [
        build_fact_member_activity_windowed(fact_bookings, members,
                                            window_days=7,  window_type="7d"),
        build_fact_member_activity_windowed(fact_bookings, members,
                                            window_days=30, window_type="30d"),
        build_fact_member_activity_windowed(fact_bookings, members,
                                            window_days=90, window_type="90d"),
    ]
    fact_member_activity_windowed = pd.concat(windowed_frames, ignore_index=True)
    log.info(f"  fact_member_activity_windowed (all windows): "
             f"{len(fact_member_activity_windowed):,} rows")

    # ------------------------------------------------------------------
    # STEP 3: TRANSFORM — Dimensions
    # ------------------------------------------------------------------
    log.info("")
    log.info("STEP 3 — TRANSFORM: DIMENSIONS")

    dim_members  = build_dim_members(members, fact_bookings)
    dim_classes  = build_dim_classes(classes)
    dim_trainers = build_dim_trainers(trainers)
    dim_time     = build_dim_time(fact_bookings, schedules)

    # ------------------------------------------------------------------
    # STEP 4: TRANSFORM — Feature / analytical tables
    # ------------------------------------------------------------------
    log.info("")
    log.info("STEP 4 — TRANSFORM: FEATURE TABLES")

    member_features_30d        = build_member_features_30d(members, fact_bookings)
    member_lifetime_summary    = build_member_lifetime_summary(members, fact_bookings)
    member_engagement_features = build_member_engagement_features(
        member_lifetime_summary, fact_bookings, members
    )
    member_cohort_assignments  = build_member_cohort_assignments(members)

    # ------------------------------------------------------------------
    # STEP 5: VALIDATE
    # ------------------------------------------------------------------
    log.info("")
    log.info("STEP 5 — VALIDATE")

    tables = {
        "fact_bookings":                 fact_bookings,
        "fact_activity_daily":           fact_activity_daily,
        "fact_class_sessions":           fact_class_sessions,
        "fact_member_activity_windowed": fact_member_activity_windowed,
        "dim_members":                   dim_members,
        "dim_classes":                   dim_classes,
        "dim_trainers":                  dim_trainers,
        "dim_time":                      dim_time,
        "member_features_30d":           member_features_30d,
        "member_lifetime_summary":       member_lifetime_summary,
        "member_engagement_features":    member_engagement_features,
        "member_cohort_assignments":     member_cohort_assignments,
    }

    all_valid = validate_all(tables)

    if not all_valid:
        log.error("Validation failed — aborting. No data has been written.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # STEP 6: LOAD
    # ------------------------------------------------------------------
    if dry_run:
        log.info("")
        log.info("STEP 6 — LOAD SKIPPED (dry-run mode)")
        log.info("All transforms and validations passed. "
                 "Re-run without --dry-run to write to the database.")
        return

    log.info("")
    log.info("STEP 6 — LOAD")

    conn = get_connection()
    try:
        load_all(conn, tables)
    except Exception as e:
        log.error(f"Load failed: {e}")
        conn.rollback()
        conn.close()
        raise
    conn.close()

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------
    log.info("")
    log.info("=" * 60)
    log.info("PIPELINE COMPLETE ✅")
    log.info("=" * 60)
    for name, df in tables.items():
        log.info(f"  {name:<40} {len(df):>8,} rows")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gym Analytics ETL Pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Transform and validate only — do not write to the database",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
