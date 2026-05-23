import streamlit as st
from queries import (
    load_churn_implication,
    load_retention,
    load_trainer_price_retention,
    load_class_type_retention
)
from analytics_utils import safe_mean, safe_groupby_mean

st.title("📊 Executive Overview")

# ---------------------------
# LOAD DATA
# ---------------------------

churn = load_churn_implication()
retention = load_retention()
price_exploration = load_trainer_price_retention()
class_retention = load_class_type_retention()

# ---------------------------
# GLOBAL SIDEBAR FILTERS
# ---------------------------

st.sidebar.header("Filters")

class_filter = None
time_filter = None

if "class_type" in churn.columns:
    class_filter = st.sidebar.selectbox(
        "Class Type",
        options=[None] + sorted(churn["class_type"].dropna().unique().tolist())
    )

if "class_time_bucket" in churn.columns:
    time_filter = st.sidebar.selectbox(
        "Time Bucket",
        options=[None] + sorted(churn["class_time_bucket"].dropna().unique().tolist())
    )

filters = {
    "class_type": class_filter,
    "class_time_bucket": time_filter
}

# apply filters
if filters:
    for col, val in filters.items():
        if val and col in churn.columns:
            churn = churn[churn[col] == val]

# ---------------------------
# KPI CALCULATIONS (SAFE)
# ---------------------------

retention_rate = retention["retained_after_30d"].mean() if "retained_after_30d" in retention.columns else 0
churn_rate = 1 - retention_rate

avg_no_show = safe_mean(churn, "no_show_rate")
avg_late_cancel = safe_mean(churn, "late_cancellation_rate")

# ---------------------------
# KPI CARDS
# ---------------------------

col1, col2, col3, col4 = st.columns(4)

col1.metric("Retention (30d)", f"{retention_rate:.2%}")
col2.metric("Churn Rate", f"{churn_rate:.2%}")
col3.metric("No-Show Rate", f"{avg_no_show:.2%}")
col4.metric("Late Cancellation", f"{avg_late_cancel:.2%}")

st.divider()

# ---------------------------
# VISUALS
# ---------------------------

st.subheader("Engagement Distribution")
if "no_show_rate" in churn.columns:
    st.bar_chart(churn["no_show_rate"])

st.subheader("Attendance Consistency")
if "attendance_consistency" in churn.columns:
    st.line_chart(churn["attendance_consistency"])

# ---------------------------
# RETENTION BY CLASS TYPE
# ---------------------------

st.subheader("Retention by Class Type")

ret_by_class = safe_groupby_mean(class_retention, "class_type", "retention_rate_30d")

if not ret_by_class.empty:
    st.dataframe(ret_by_class)
    st.bar_chart(ret_by_class, x="class_type", y="retention_rate_30d")