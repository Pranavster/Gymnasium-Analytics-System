import streamlit as st
from queries import load_churn_implication, load_trainer_price_retention
from analytics_utils import safe_groupby_mean

st.title("🔍 Retention & Behavior Analysis")

churn = load_churn_implication()
price_retention = load_trainer_price_retention()

# ---------------------------
# FILTERS
# ---------------------------

st.sidebar.header("Filters")

class_filter = None
time_filter = None

if "class_type" in churn.columns:
    class_filter = st.sidebar.selectbox(
        "Class Type",
        options=[None] + sorted(churn["class_type"].dropna().unique().tolist())
    )

if class_filter and "class_type" in churn.columns:
    churn = churn[churn["class_type"] == class_filter]

# ---------------------------
# VISUALS
# ---------------------------

st.subheader("No-Show Behavior")
st.bar_chart(churn["no_show_rate"])

st.subheader("Late Cancellation Behavior")
st.bar_chart(churn["late_cancellation_rate"])

st.divider()

# ---------------------------
# PRICE IMPACT
# ---------------------------

st.subheader("Price vs Engagement")

ret_by_price = safe_groupby_mean(price_retention, "avg_session_price", "tenure_days")

if not ret_by_price.empty:
    st.dataframe(ret_by_price)
    st.bar_chart(ret_by_price, x="avg_session_price", y="tenure_days")