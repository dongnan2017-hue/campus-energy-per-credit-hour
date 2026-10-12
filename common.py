"""Shared loading for the app pages: map buildings and the mapped Fall 2026 schedule."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import campus_data as cd


@st.cache_data
def load() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    buildings = cd.load_buildings()
    using_real = cd.REAL_PATH.exists()
    schedule, _warnings = cd.normalize_schedule(pd.read_csv(cd.REAL_PATH if using_real else cd.SAMPLE_PATH, dtype=str))
    schedule = cd.attach_departments(schedule)
    mapping, _unmatched = cd.match_buildings(schedule["building"].unique(), buildings["name"].tolist())
    schedule = schedule.assign(building=schedule["building"].map(lambda b: mapping.get(b, b)))
    return buildings, schedule, ("fall2026" if using_real else "sample")
