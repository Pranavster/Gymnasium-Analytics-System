# KPI Review
### Gymnasium Analytics System — KPI Inventory, Gaps & Recommendations

---

## Implemented KPIs

The following KPIs are fully defined in `sql/views.sql` and queried in `dashboard/queries.py`.

| KPI | Definition | Source View |
|---|---|---|
| Retention Rate (30d) | Members active in days 30–60 post-signup / total members | `vw_retained_after_30d_by_member` |
| Churn Rate (30d) | 1 − Retention Rate | Derived in `1_Executive.py` |
| No-Show Rate | Uncancelled, unattended bookings / total bookings | `vw_churn_implication` |
| Late Cancellation Rate | Cancellations < 24h before class / total bookings | `vw_churn_implication` |
| Booking Frequency Score | min(bookings / 8.0, 1.0) | `vw_churn_implication` |
| Attendance Consistency | Attended / (bookings − all cancellations) | `vw_churn_implication` |
| Attendance Rate by Time Slot | Attended / total bookings, grouped by morning / afternoon / evening | `vw_time_attendance_rate` |
| Avg Fill Rate by Time Slot | Avg attended / session capacity, grouped by time slot | `vw_average_utilization` |
| Retention Rate by Class Type | 30d retention rate segmented by first-week class category | `vw_class_type_retention_association` |
| Churn Rate by Capacity Tier | Churn rate for high (≥20) vs low (<20) capacity class attendees | `vw_capacity_churn_rates` |
| Avg Session Price vs Tenure | Trainer session pricing tiers (low / medium / high) vs member tenure days | `vw_trainer_price_churn_features` |
| Revenue per Member by Tier | Total payments / distinct members, grouped by membership tier | `vw_membership_per_capita_revenue` |
| Revenue by Class Type | Total and per-session revenue attributed to each class type | `vw_class_type_revenue` (aliased `class_type_revenue`) |
| Trainer Tenure vs Revenue | Total trainer session revenue vs tenure days since hire | `vw_tenure_influence` |
| Time Slot Utilization | Attendance rate + avg fill rate per time slot over trailing 30 days | `vw_time_slot_utilization` |

---

## Identified Gaps

The following gaps were found through code review of `dashboard/queries.py`, the Streamlit pages, and `sql/views.sql`. These are areas where the data or view exists but the KPI is not fully surfaced or is surfaced in a suboptimal way.

**1. Revenue views have no dashboard page.**
`vw_membership_per_capita_revenue`, `vw_class_type_revenue`, and `vw_tenure_influence` are all implemented in SQL and loaded in `queries.py` (`load_class_type()`), but no Streamlit page renders them. A fourth dashboard page — "Revenue" — would complete analytical coverage across the four business domains (retention, engagement, operations, revenue).

**2. Trainer fill rate view has no dashboard panel.**
`vw_trainer_fill_rate` is referenced in the project documentation but has no corresponding `load_*` function in `queries.py` and no dashboard panel. The data needed to build this view exists in `fact_class_sessions`.

**3. 'Price vs Engagement' chart uses a continuous grouping variable.**
In `2_Retention.py`, the price–tenure chart groups by `avg_session_price` (a continuous float). The view `vw_trainer_price_churn_features` already contains a pre-computed `price_tier` column (low / medium / high). Grouping by `price_tier` would produce cleaner, more interpretable bar charts.

**4. Engagement Distribution and Attendance Consistency are raw per-member series.**
Both charts in `1_Executive.py` plot a flat series of per-member values with no aggregation. As raw distributions they are dense and difficult to read. Grouping by membership tier or cohort month would make these panels actionable.

**5. `avg_booking_lead_time` is computed in `member_features_30d` but never exposed.**
The pipeline stores each member's average time between booking and class start. This is a meaningful engagement signal (longer lead time → more committed member) but it does not appear in any dashboard view or query.

---

## Recommended KPI Additions

> The following KPIs are **recommendations only**. They are not currently implemented. They are clearly labeled here to distinguish them from the implemented KPIs above.

| Suggested KPI | Definition | Rationale |
|---|---|---|
| Days Since Last Booking | `CURRENT_DATE − max(booking_time)` per member | Early churn warning; easily derived from `fact_bookings` |
| Cohort Retention Curve | Active member count per cohort month over sequential months post-signup | Standard retention benchmarking; infrastructure exists in `member_cohort_assignments` |
| Class Diversity Score | Distinct class types attended per member in trailing 30 days | Engagement depth signal; members attending multiple class types may churn less |
| Avg Booking Lead Time (exposed) | `avg_booking_lead_time` from `member_features_30d` surfaced in dashboard | Already computed — only requires a `load_` function and chart |
| Peak Hour Demand Score | Sessions at >85% fill rate as % of all sessions, grouped by hour of day | Identifies sustained capacity pressure points for scheduling decisions |
| Waitlist Conversion Rate | Waitlist bookings confirmed / total waitlist entries | Requires waitlist data capture in the OLTP layer (not currently modeled) |
| 7-Day Re-engagement Rate | Members who book again within 7 days of a no-show event | Measures whether no-shows are recoverable; requires `fact_bookings` join logic |
| Revenue per Session (by class type) | Total trainer session revenue / session count, by class type | Partially defined in `vw_class_type_revenue`; needs correct join to payments |
