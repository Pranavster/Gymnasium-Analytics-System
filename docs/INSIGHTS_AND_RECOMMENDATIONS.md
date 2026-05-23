# Insights & Recommendations
### Gymnasium Analytics System — Analytical Findings

> **Data note:** All findings are derived from synthetically generated data. Metrics are illustrative of the analytical framework and methodology. No figures have been invented beyond what the dashboard and SQL views produced.

---

## Executive Summary

The dashboard surfaces four headline KPIs across the member base for the trailing 30-day window.

| KPI | Value | Context |
|---|---|---|
| Retention (30d) | 20.60% | Synthetically low — random data artifact; methodology is valid |
| Churn Rate | 79.40% | Inverse of retention; not operationally realistic |
| No-Show Rate | 21.45% | Most actionable headline metric |
| Late Cancellation Rate | 9.92% | Within a reasonable operational range |

The retention and churn figures are unrealistically extreme and are a direct consequence of the random data generation process. The no-show rate of 21.45% is the most meaningful headline metric: no-shows represent confirmed capacity waste — slots occupied on paper but delivering no attendance value.

---

## Retention & Churn Analysis

### 30-Day Retention by Class Type

Members who attended a given class type within their first 7 days of membership showed the following 30-day retention rates:

| Class Type | Retention Rate (30d) |
|---|---|
| Flexibility | 92.86% |
| Cardio | 82.05% |
| HIIT | 76.00% |
| Strength | 75.00% |

**Interpretation:** Flexibility classes are the strongest early-engagement driver of 30-day retention in this dataset. The gap between flexibility (92.86%) and strength (75.00%) is 17.86 percentage points — substantial enough to inform scheduling and new-member onboarding decisions. Members whose first-week experience includes a flexibility class are meaningfully more likely to remain active through day 60.

Strength classes show the lowest retention rate, trailing flexibility by nearly 18 points. This warrants further investigation: is the scheduling of strength classes less convenient, or do they attract a different member profile (e.g., drop-in, shorter-tenure)?

### Churn Signal Features

The `vw_churn_implication` view computes the following behavioral signals per member over the trailing 30 days. These form the basis for a future churn prediction model:

- **Booking frequency score** — normalized bookings relative to an 8-booking ceiling
- **Attendance consistency** — attended sessions as a share of non-cancelled bookings
- **Late cancellation rate** — cancellations within 24 hours of session start / total bookings
- **No-show rate** — unattended, uncancelled bookings / total bookings

These features are also pre-computed for the first 30 days post-signup in `member_features_30d`, enabling cohort-level early churn signal analysis.

---

## Engagement & Behavioral Insights

### No-Show Rate (21.45%)

A no-show occurs when a member books a class, does not cancel, and does not attend. At 21.45%, approximately 1 in 5 booked slots delivers no attendance value. This is distinct from cancellations: cancellations at least free the slot with some lead time. No-shows provide no opportunity for the gym to reallocate the slot.

### Late Cancellation Rate (9.92%)

Late cancellations (within 24 hours of class start) constitute 9.92% of all bookings. Combined with the no-show rate, approximately **31% of all booked slots generate no attendance value within the 24-hour scheduling window**.

### Engagement Distribution & Attendance Consistency Charts

The per-member engagement distribution and attendance consistency charts display high variance across the member base. This is characteristic of synthetic data with random behavioral assignment and is not interpretable as a meaningful behavioral cluster. In a real dataset, these distributions would be used to segment members into engagement tiers for targeted retention interventions.

---

## Operational Performance — Classes & Scheduling

### Attendance Rate by Time Slot

| Time Slot | Attendance Rate | Avg Fill Rate |
|---|---|---|
| Afternoon (12:00–16:30) | 70.59% | 70% |
| Evening (16:30–19:00) | 67.92% | 69% |
| Morning (06:00–12:00) | 64.96% | 63% |

**Interpretation:** Afternoon sessions consistently outperform evening and morning in both attendance rate and fill rate. The ~7 percentage point gap between afternoon and morning fill rates suggests mornings are the least efficiently utilized scheduling band. This may reflect genuine member preference for afternoon sessions, or simply that afternoon classes are more heavily promoted or better staffed.

---

## Business Recommendations

### 1. Prioritize Flexibility Classes in Early Member Onboarding

Flexibility classes drive the highest 30-day retention rate (92.86%). The onboarding sequence and first-week scheduling should ensure new members are exposed to at least one flexibility class early in their membership.

- Feature flexibility classes prominently in new member welcome communications
- Ensure at least one flexibility session is available across each time slot daily
- Consider making a flexibility class part of a guided onboarding programme

### 2. Reduce No-Show Rate Through Policy and Technology

A 21.45% no-show rate represents confirmed resource waste. Unlike churn, no-shows are a near-term behavior addressable through direct mechanisms:

- Implement SMS/push reminders 24 hours and 2 hours before class
- Activate a waitlist system to reallocate no-show slots in real time
- Introduce a no-show penalty policy (e.g., temporary booking suspension) after a defined threshold

### 3. Expand Afternoon Session Availability

Afternoon slots deliver the highest attendance rate and fill rate. This pattern suggests concentrated member demand in this window, and potentially unmet capacity.

- Increase the number of class sessions scheduled between 12:00 and 16:30
- If trainer capacity is constrained, consider redistributing from the morning band (lowest fill rate at 63%) to the afternoon band

### 4. Develop an Early-Warning Churn Score

The `member_features_30d` and `member_engagement_features` tables already contain the behavioral signals needed for a simple churn prediction model. The next analytical step is to join these features with the `churned` flag from `dim_members` and train a binary classifier.

Suggested features: `booking_count_30d`, `attendance_rate_30d`, `no_show_rate_30d`, `late_cancel_rate_30d`, `avg_booking_lead_time`
Target: `churned` (binary) from `dim_members`
Use case: Flag members with elevated predicted churn probability for proactive outreach before day 30.

### 5. Investigate Strength Class Retention Lag

Strength classes show the lowest 30-day retention (75.00%), trailing flexibility by 17.86 points. Before de-prioritizing strength classes, investigate confounding factors:

- Are strength classes disproportionately scheduled in the lower-performing morning slot?
- Do strength class attendees skew toward shorter-tenure or drop-in members?
- Is the class type itself a retention driver, or is it a proxy for another variable?

Resolving this distinction will determine whether the recommendation is to reschedule, repromote, or restructure the strength class offering.
