import streamlit as st
from queries import load_time_attendance, load_time_attendance_utilization

st.title("⚙️ Operations & Class Performance")

attendance_df = load_time_attendance()
util_df = load_time_attendance_utilization()

st.subheader("Class Attendance")

if "class_time_bucket" in attendance_df.columns:
    st.dataframe(attendance_df)
    st.bar_chart(attendance_df, x="class_time_bucket", y="attendance_rate")

st.subheader("Capacity Utilization")

if "class_time_bucket" in util_df.columns:
    st.dataframe(util_df)
    st.bar_chart(util_df, x="class_time_bucket", y="avg_fill_rate")
