# Debug & Data Integrity Notes
### Gymnasium Analytics System — Pipeline Issue Analysis

> All analysis in this document is based on code review only. No SQL logic, Python code, or queries have been modified. Issues are documented here for resolution in the next development iteration.

---

## Issue 1: `'closed'` Value Appearing in Time Bucket Charts

### Symptom

The Operations page class attendance chart displayed a `'closed'` category alongside `'morning'`, `'afternoon'`, and `'evening'`. This value was not present in `vw_average_utilization` but appeared when consuming `vw_time_attendance_rate`.

### Root Cause

The two time-bucket views use inconsistent `CASE` statement boundaries for the evening window:

| View | Evening upper bound | Overflow label |
|---|---|---|
| `vw_time_attendance_rate` | Before 19:00 → `ELSE 'closed'` | `'closed'` — included in output |
| `vw_average_utilization` | Before 21:00 → `ELSE 'off_hours'` | `'off_hours'` — filtered out with `WHERE` clause |

Sessions scheduled between 19:00 and 21:00 fall into `'closed'` in `vw_time_attendance_rate` but are labeled `'off_hours'` and filtered in `vw_average_utilization`. Because `3_Operations.py` consumes `vw_time_attendance_rate` without pre-filtering, `'closed'` surfaces as a category in the chart.

### Resolution Approach (do not modify SQL)

Two options, in order of preference:

1. **Align view definitions** — standardize both views on the same evening boundary (21:00) and overflow label (`'off_hours'`), then add a `WHERE class_time_bucket != 'off_hours'` filter consistent with `vw_average_utilization`.
2. **Filter in the dashboard layer** — add a `.query("class_time_bucket != 'closed'")` filter in `queries.py` before the DataFrame is returned to `3_Operations.py`.

---

## Issue 2: `schedule_id` Dropped from `fact_bookings` After Transform

### Symptom

`build_fact_class_sessions()` in `transform_bookings.py` must re-join `fact_bookings` back to the `schedules` table in order to recover `schedule_id` for session-level aggregation. This re-join happens inside the transform function, adding redundant computation.

### Root Cause

In `build_fact_bookings()`, the final column selection explicitly excludes `schedule_id`:

```python
result = fact[[
    "booking_id", "member_id", "class_id", "trainer_id",
    "booking_time", "class_time", "status", "cancellation_time",
    "is_cancelled", "is_late_cancel", "is_no_show", "is_attended",
]].copy()
```

`schedule_id` is used as a join key during fact construction but is not carried into the output DataFrame. When `build_fact_class_sessions()` later needs to count attended bookings per session, it re-derives the session mapping by joining on the composite key `(class_id, trainer_id, class_time)`.

### Impact

This re-join adds computational redundancy and introduces a potential many-to-one mismatch risk: if any `(class_id, trainer_id, class_time)` combination maps to more than one schedule row, the join will fan out and produce incorrect attended counts. In the current synthetic dataset this is unlikely, but it is a structural fragility.

### Resolution Approach (do not modify code)

Retain `schedule_id` in the `fact_bookings` output column list and add the corresponding column to the `fact_bookings` DDL in `sql/Metrics_def.sql`. No SQL view logic would be affected.

---

## Issue 3: SQL Syntax Errors in `KPI_definitions_v2.sql`

### Symptom

Multiple queries in `sql/KPI_definitions_v2.sql` use invalid PostgreSQL syntax and would fail if executed directly against the database.

### Specific Error

The keyword `BETWEEN` is used as a standalone interval modifier in multiple places:

```sql
-- INVALID (appears throughout KPI_definitions_v2.sql)
CURRENT_DATE - between '30 days'

-- CORRECT PostgreSQL syntax
CURRENT_DATE - INTERVAL '30 days'
```

### Affected Queries

This error appears in: `churn_rate_30d_view`, `retention_rate_30d_view`, the rolling metrics CTE, the `cancellation_rate` query, the `no_show_rate` query, the `inactive_members` view, and the class diversity query.

### Impact

`KPI_definitions_v2.sql` is a development draft / prototype file, not a deployed artifact. The production views in `sql/views.sql` use the correct `INTERVAL` syntax throughout and are entirely unaffected. There is no operational impact.

---

## Issue 4: `fact_bookings` Missing `class_session_id` for View Joins

### Symptom

The views `vw_time_slot_utilization` and `vw_time_attendance_rate` join `fact_bookings` to `fact_class_sessions` on `fb.class_session_id = fct.class_session_id`. However, `fact_bookings` as produced by the transform layer does not contain a `class_session_id` column (see Issue 2).

### Root Cause

This is the direct downstream consequence of Issue 2. If `fact_bookings` does not carry `class_session_id`, the join in these views produces zero rows or incorrect results, unless `class_session_id` is added during the load step or the view is rewritten to join on the composite key `(class_id, trainer_id, class_time)`.

### Impact

These two views would return empty or incorrect results unless the `class_session_id` column is present in the loaded `fact_bookings` table. This affects the time-slot attendance and utilization panels in `3_Operations.py`.

### Resolution Approach (do not modify code)

Resolving Issue 2 — retaining `schedule_id` in `fact_bookings` and aliasing it as `class_session_id` in the DDL — would also resolve this issue. The view SQL itself does not need to change.

---

## Validation Coverage Summary

The `etl/validation.py` module runs the following checks before any data is written. If any check fails, the pipeline aborts with no partial writes.

| Check | Tables Covered |
|---|---|
| No null primary keys | All 12 analytical tables |
| No duplicate PKs | All 12 analytical tables |
| Rate columns in [0.0, 1.0] | `fact_activity_daily`, `fact_class_sessions`, `fact_member_activity_windowed`, `member_features_30d`, `member_lifetime_summary`, `member_engagement_features` |
| `booking_time ≤ class_time` | `fact_bookings` |
| Status values valid (`attended` / `cancelled` / `no_show` only) | `fact_bookings` |
| `is_attended` XOR `is_cancelled` | `fact_bookings` |
| `is_late_cancel` implies `is_cancelled` | `fact_bookings` |
| `attended + cancelled + no_show = bookings` | `fact_activity_daily` |
| No gaps in date sequence | `dim_time` |
| `churn_date` null when `churned = False` | `dim_members` |
| `tenure_days ≥ 0` | `member_lifetime_summary` |
