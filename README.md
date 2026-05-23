# Gymnasium Analytics System
### A Full-Stack Analytics Engineering Portfolio Project

---

## Overview

This project is an end-to-end analytics engineering system built for a gymnasium context. It covers the full data stack: synthetic data generation, relational schema design, an idempotent ETL pipeline, dimensional modeling, KPI engineering via SQL views, and an interactive Streamlit dashboard.

The three primary analytical goals are:

- **Improve member retention** by identifying early behavioral signals of churn
- **Reduce no-show and late cancellation rates** through engagement pattern analysis
- **Optimize class scheduling** by understanding time-slot utilization and fill rates

> **Data note:** All data is synthetically generated. Figures such as the 79.40% churn rate are artifacts of random generation and are not representative of real-world gym performance. The analytical infrastructure and KPI definitions are production-grade.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Database | PostgreSQL |
| ETL Orchestration | Python — pandas, psycopg2 |
| Data Modeling | Star schema (facts + dimensions + feature tables) |
| Analytics Layer | SQL views (PostgreSQL) |
| Dashboard | Streamlit (Python) |
| Environment Config | python-dotenv |

---

## Repository Structure

```
gymnasium_analytics/
│
├── etl/
│   ├── extract.py              # Reads 9 raw OLTP tables from PostgreSQL
│   ├── transform_bookings.py   # Builds fact tables (bookings, sessions, activity)
│   ├── transform_members.py    # Builds dimension + feature tables
│   ├── validation.py           # 30+ pre-load data quality checks
│   ├── load.py                 # Idempotent truncate-and-insert loader
│   └── run.py                  # Pipeline orchestrator (--dry-run supported)
│
├── sql/
│   ├── Metrics_def.sql         # OLTP schema DDL (tables + constraints)
│   ├── KPI_definitions_v2.sql  # KPI query prototypes (development drafts)
│   └── views.sql               # Production analytics views (10 KPI views)
│
├── dashboard/
│   ├── queries.py              # Cached Streamlit data loaders
│   ├── 1_Executive.py          # Page 1: Executive overview
│   ├── 2_Retention.py          # Page 2: Retention & behavior analysis
│   └── 3_Operations.py         # Page 3: Operations & class performance
│
├── docs/
│   ├── INSIGHTS_AND_RECOMMENDATIONS.md
│   ├── KPI_REVIEW.md
│   └── DEBUG_AND_DATA_INTEGRITY.md
│
└── README.md
```

---

## Architecture & Data Flow

```
PostgreSQL (OLTP: gym_analytics schema)
          │
          ▼
      etl/extract.py
      Reads 9 raw tables: members, trainers, classes, schedules,
      bookings, cancellations, attendance, payments, trainer_sessions
          │
          ▼
      etl/transform_bookings.py   →  fact_bookings
                                     fact_activity_daily
                                     fact_class_sessions
                                     fact_member_activity_windowed (7d / 30d / 90d)

      etl/transform_members.py    →  dim_members
                                     dim_classes
                                     dim_trainers
                                     dim_time
                                     member_features_30d
                                     member_lifetime_summary
                                     member_engagement_features
                                     member_cohort_assignments
          │
          ▼
      etl/validation.py
      30+ checks: nulls, duplicates, rate ranges, flag logic,
      referential integrity, date spine continuity
          │
          ▼
      etl/load.py
      Truncate → batch insert (psycopg2 execute_values)
      Fully idempotent — safe to re-run at any time
          │
          ▼
PostgreSQL (Analytics Schema: gym_analytics)
          │
          ▼
      sql/views.sql
      10 aggregated KPI views across retention, engagement,
      operations, and revenue
          │
          ▼
      Streamlit Dashboard (3 pages)
```

---

## Data Model

### Fact Tables

| Table | Grain | Key Columns |
|---|---|---|
| `fact_bookings` | One row per booking | `booking_id`, `member_id`, `class_id`, `is_attended`, `is_cancelled`, `is_late_cancel`, `is_no_show`, `status` |
| `fact_activity_daily` | One row per (member, date) | `date`, `member_id`, `bookings`, `attended`, `cancelled`, `no_show`, `attendance_rate` |
| `fact_class_sessions` | One row per scheduled session | `class_session_id`, `trainer_id`, `fill_rate`, `attended_count`, `start_time`, `end_time` |
| `fact_member_activity_windowed` | One row per (member, window) | `member_id`, `window_start`, `window_type` (7d / 30d / 90d), `attendance_rate` |

### Dimension Tables

| Table | Description |
|---|---|
| `dim_members` | Member attributes, signup date, churn status, churn date, membership type |
| `dim_classes` | Class type, capacity, duration (minutes) |
| `dim_trainers` | Trainer hire date, specialization |
| `dim_time` | Date spine with `day_of_week`, `week_of_year`, `month`, `quarter`, `is_weekend` |

### Feature & Analytical Tables

| Table | Description |
|---|---|
| `member_features_30d` | First-30-day rates per member: bookings, attendance, cancellation, no-show, avg lead time |
| `member_lifetime_summary` | Full-tenure stats: total bookings, attendance/cancellation/no-show rates, tenure days |
| `member_engagement_features` | Normalized engagement scores for churn/retention modeling |
| `member_cohort_assignments` | Member-to-cohort mapping by signup month |

---

## Dashboard Description

The Streamlit dashboard has three pages, each backed by cached SQL view queries in `dashboard/queries.py`.

**Page 1 — Executive Overview** (`1_Executive.py`)
KPI cards: retention rate (30d), churn rate, no-show rate, late cancellation rate. Charts: engagement distribution, attendance consistency. Table + bar chart: retention rate by class type.

**Page 2 — Retention & Behavior Analysis** (`2_Retention.py`)
Per-member no-show and late cancellation distributions, filterable by class type. Trainer session pricing vs. member tenure chart.

**Page 3 — Operations & Class Performance** (`3_Operations.py`)
Attendance rate and average fill rate by time slot (morning / afternoon / evening).

---

## Key KPIs

| KPI | Definition |
|---|---|
| Retention Rate (30d) | Members active in days 30–60 post-signup / total members |
| Churn Rate | 1 − Retention Rate |
| No-Show Rate | Uncancelled, unattended bookings / total bookings (30d window) |
| Late Cancellation Rate | Cancellations within 24h of class start / total bookings |
| Attendance Rate | Attended / non-cancelled bookings |
| Avg Fill Rate | Attended count / session capacity (capped at 1.0) |
| Retention by Class Type | 30d retention rate segmented by first-week class category |
| Booking Frequency Score | min(bookings / 8.0, 1.0) — normalized engagement signal |

---

## How to Run

### 1. Prerequisites

```bash
pip install pandas psycopg2-binary python-dotenv streamlit
```

### 2. Environment Setup

Create a `.env` file in the project root:

```env
DB_HOST=localhost
DB_PORT=5433
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password
```

### 3. Run the ETL Pipeline

```bash
# Full pipeline: transform + validate + load
python etl/run.py

# Dry run: transform + validate only (no DB writes)
python etl/run.py --dry-run
```

### 4. Launch the Dashboard

```bash
streamlit run dashboard/1_Executive.py
```

---

## Data Quality Validation

The pipeline runs 30+ automated checks before any data is written. If any check fails, the pipeline aborts with no partial writes. Key checks include:

- No null values on primary and foreign keys across all 12 analytical tables
- No duplicate PKs on any fact or dimension table
- All rate columns strictly in [0.0, 1.0]
- `booking_time` always precedes `class_time` in `fact_bookings`
- `is_attended` and `is_cancelled` are mutually exclusive
- `is_late_cancel` implies `is_cancelled`
- `attended + cancelled + no_show = bookings` in `fact_activity_daily`
- No gaps in the `dim_time` date spine
- `churn_date` is null whenever `churned = False`
- `tenure_days >= 0` in `member_lifetime_summary`
=======
# Gymnasium-Analytics-System
This project is an end-to-end analytics engineering system built for a gymnasium context. It covers the full data stack: synthetic data generation, relational schema design, ETL pipeline, dimensional modeling, KPI engineering via SQL views, and an interactive Streamlit dashboard.
