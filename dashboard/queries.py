# queries.py
import streamlit as st
from db import run_query


# ---------------------------
# KPI LAYER LOADERS (cached)
# ---------------------------

@st.cache_data
def load_churn_implication():
    return run_query("""
        SELECT * 
        FROM gym_analytics.vw_churn_implication
    """)


@st.cache_data
def load_retention():
    return run_query("""
        SELECT * 
        FROM gym_analytics.vw_retained_after_30d_by_member
    """)


@st.cache_data
def load_trainer_price_retention():
    return run_query("""
        SELECT * 
        FROM gym_analytics.vw_trainer_price_churn_features
    """)


@st.cache_data
def load_capacity_churn():
    return run_query("""
        SELECT *
        FROM gym_analytics.vw_capacity_churn_rates
    """)


@st.cache_data
def load_time_utilization():
    return run_query("""
        SELECT *
        FROM gym_analytics.vw_time_slot_utilization
    """)


@st.cache_data
def load_time_attendance():
    return run_query("""
        SELECT *
        FROM gym_analytics.vw_time_attendance_rate
    """)


@st.cache_data
def load_time_attendance_utilization():
    return run_query("""
        SELECT *
        FROM gym_analytics.vw_average_utilization
    """)


@st.cache_data
def load_class_type():
    return run_query("""
        SELECT *
        FROM gym_analytics.vw_class_type_revenue
    """)


@st.cache_data
def load_class_type_retention():
    return run_query("""
        SELECT *
        FROM gym_analytics.vw_class_type_retention_association
    """)