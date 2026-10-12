"""Entry point: Albion College classroom energy and cost explorer (unofficial student project).

Run:  streamlit run app.py      (or double-click run_campus.bat)
"""
import streamlit as st

st.set_page_config(page_title="Campus energy and classrooms", page_icon=None, layout="wide")

pages = [
    st.Page("pages/2_Cost_per_credit_hour.py", title="Energy cost per credit hour", default=True),
    st.Page("campus_map.py", title="Campus map: activity and energy"),
    st.Page("pages/1_Energy_cost_Fall_2026.py", title="Energy cost, Fall 2026"),
    st.Page("pages/3_Data_sources.py", title="Data sources"),
    st.Page("pages/4_Methodology.py", title="Methodology (diagram)"),
    st.Page("pages/5_Room_walkthrough.py", title="Room 215 walkthrough"),
]
st.navigation(pages).run()
