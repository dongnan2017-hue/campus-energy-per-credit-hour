"""Data sources page: every source with its link, how it was obtained, terms and limits."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

import sources_data as sd

st.title("Data sources")
st.caption(f"Everything the app uses, with links. Accessed {sd.ACCESSED}. Unofficial student project, "
           "not affiliated with or endorsed by Albion College.")

tab1, tab2, tab3, tab4 = st.tabs(["Sources", "Assumptions", "Not used", "Files in this project"])

with tab1:
    st.markdown("Each row says where a number or file came from and how it was obtained. "
                "**Only the campus electricity total is a real energy figure; everything else is public context or arithmetic.**")
    df = pd.DataFrame(sd.SOURCES)
    st.dataframe(df, hide_index=True, height=520,
                 column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")})
    st.markdown("**Sources by role**")
    st.markdown(
        "- **Energy input:** Albion article (14 million kWh a year)\n"
        "- **Buildings and floors:** OpenStreetMap\n"
        "- **Classes, rooms, times, credits, titles, departments:** Registrar public course search\n"
        "- **Class days and credit conversion:** Registrar calendar and FAQ\n"
        "- **Winter heating shape:** NOAA climate normals\n"
        "- **Price and national comparison:** U.S. EIA")

with tab2:
    st.markdown("These are **choices made by the project**, not data. Each can be changed where indicated.")
    st.dataframe(pd.DataFrame(sd.ASSUMPTIONS), hide_index=True, height=480)
    st.markdown("**Limits**")
    for line in sd.LIMITS:
        st.markdown(f"- {line}")

with tab3:
    st.markdown("Things that were considered and deliberately **not** used.")
    st.dataframe(pd.DataFrame(sd.NOT_USED), hide_index=True)

with tab4:
    st.markdown("Data files stored with the app (in the `data` folder).")
    data_dir = Path(__file__).resolve().parent.parent / "data"
    rows = []
    for f in sorted(data_dir.iterdir()):
        if not f.is_file():
            continue
        n = ""
        try:
            if f.suffix.lower() == ".csv":
                n = f"{len(pd.read_csv(f)):,} rows"
            elif f.suffix.lower() == ".geojson":
                import json
                n = f"{len(json.loads(f.read_text(encoding='utf-8'))['features']):,} features"
        except Exception:
            n = ""
        rows.append({"File": f.name, "Size": f"{f.stat().st_size / 1024:,.0f} KB", "Contents": n,
                     "Last changed": dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption("`course_meetings_sample.csv` is synthetic test data and is not used while the real schedule file exists. "
               "Re-download the schedule any time with `python fetch_schedule.py`.")
