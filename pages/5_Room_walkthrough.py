"""Page: step-by-step walkthrough of how one classroom's electricity cost is calculated (Olin Hall room 215)."""
from pathlib import Path

import streamlit as st

HTML = Path(__file__).resolve().parent.parent / "docs" / "room215_method.html"
st.iframe(HTML, height=6200)
