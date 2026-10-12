"""Streamlit screen for the modeled energy estimate, plus the shared Sources panel."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import energy as en

ATTRIBUTION = ("Map data (c) [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL). "
               "Basemap (c) [CARTO](https://carto.com/attributions). "
               "Unofficial student project; not affiliated with or endorsed by Albion College.")

SOURCES_MD = """
**Data sources (all public; accessed 2026-10-12)**

1. **Building outlines and floor counts**: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), licensed under the
   [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/). Fetched through the
   [Overpass API](https://overpass-api.de/) and located with [Nominatim](https://nominatim.openstreetmap.org/).
   Basemap tiles: [CARTO basemaps](https://carto.com/basemaps/), data (c) OpenStreetMap contributors.
2. **Class schedule (Fall 2026, term code 202630)**: Albion College Office of the Registrar,
   [Course Schedules](https://www.albion.edu/offices/registrar/course-schedules/), read from the public
   [course search tool](https://adminpagesprod02.albion.edu:7443/StudentRegistrationSsb/ssb/term/termSelection?mode=search).
   Only course code, building, room, day and start/end time are kept (no titles, instructors or enrollment).
3. **Campus electricity**: Albion College, [Albion College Joins Climate Leadership Network, Commits to Action](https://www.albion.edu/post/albion-college-joins-climate-leadership-network-commits-to-action/)
   (by Chuck Carlson, posted December 18, 2020): "the College uses about 14 million kilowatt hours." The article gives no period
   (assumed to be one year) and the figure is rounded and dated.
4. **Winter heating shape**: NOAA National Centers for Environmental Information,
   [U.S. Climate Normals 1991-2020 (monthly)](https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals),
   field MLY-HTDD-NORMAL for Jackson Reynolds Field, MI (station USW00014833), about 21 km from campus:
   [data file](https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/access/USW00014833.csv).
5. **National comparison**: U.S. Energy Information Administration,
   [Commercial Buildings Energy Consumption Survey 2018, Table E6](https://www.eia.gov/consumption/commercial/data/2018/ce/pdf/e6.pdf)
   (release date December 2022): education buildings, 9.4 kWh of electricity per square foot per year
   (in buildings using electricity for the end use).
6. **Term dates (class days)**: Albion College Office of the Registrar,
   [Academic Calendar](https://www.albion.edu/offices/registrar/academic-calendar/): Fall 2026 classes August 24 to December 4;
   no classes September 7, October 12-13 and November 25-28.
7. **Electricity price (cost page)**: U.S. EIA, [2024 Average Monthly Bill - Commercial](https://www.eia.gov/electricity/sales_revenue_price/pdf/table_5B.pdf)
   (data from forms EIA-861): Michigan 14.01 cents/kWh (U.S. total 12.75). Albion's actual supplier rate is not public and may differ.
8. **Credit hours**: Albion College Office of the Registrar,
   [Frequently Asked Questions](https://www.albion.edu/offices/registrar/frequently-asked-questions/): "one unit of credit is equal to four
   semester hours of credit." Credit units and aggregate section enrollment counts come from the same public
   [course search](https://adminpagesprod02.albion.edu:7443/StudentRegistrationSsb/ssb/term/termSelection?mode=search) (no student information).
9. **Unit conversion**: 1 MMBtu = 293.07 kWh ([EIA units and calculators](https://www.eia.gov/energyexplained/units-and-calculators/)); 1 ft2 = 0.0929 m2.

**How the estimate is built (modeled, not metered)**
- *Floor area* = building footprint from OpenStreetMap x number of floors (OpenStreetMap floor count, or the highest floor implied by
  room numbers in the schedule, or 1). No floor plans are used.
- *Electricity*: the campus total (source 3) is shared across the modeled buildings by floor area. A share (default 30%) varies with how
  many class hours the building hosts; buildings with no scheduled classes get the average.
- *Heating*: no public heating total was found, so heating is shown as each building's **share of the annual campus heating**, allocated by area.
  A share (default 80%) follows monthly heating degree days; the rest is flat (hot water, kitchens). If you enter a total yourself it is shown in MMBtu.
  Which heating system each building uses is not public, so none is claimed.
- *Rooms*: a room's yearly estimate = its building's electricity per m2 x a typical classroom area (an **assumption**, default 60 m2, adjustable),
  weighted up or down by how many hours the room is scheduled. Area and an intensity multiplier can be set per building in the sidebar. While a class runs, the room draws the constant part plus the class-driven part. Relative values only.
- Software: [Streamlit](https://streamlit.io/), [pydeck / deck.gl](https://deckgl.readthedocs.io/), [pandas](https://pandas.pydata.org/), [Altair](https://altair-viz.github.io/).
  Licenses are listed in THIRD_PARTY_NOTICES.md.
"""


def sources_panel(open_: bool = False) -> None:
    with st.expander("Sources and assumptions", expanded=open_):
        st.markdown(SOURCES_MD)


def attribution() -> None:
    st.caption(ATTRIBUTION)


@st.cache_data(show_spinner=False)
def _compute(_buildings, _schedule, key: str, params: tuple):
    p = en.Params(*params)
    model = en.building_model(_buildings, _schedule, p)
    return model, en.monthly(model, p), en.room_model(_schedule, model, p)


def default_params() -> tuple:
    return (en.ALBION_ELEC_KWH, 1.0, 0.0, 0.8, 0.3, 60.0, 0.5, ())


def sidebar_params(scheduled_buildings: list[str] | None = None) -> tuple:
    """Energy assumptions in the sidebar. Returns the parameter tuple shared by the map and the details section."""
    with st.sidebar.expander("Energy assumptions", expanded=False):
        elec = st.number_input("Campus electricity (kWh/yr)", value=float(en.ALBION_ELEC_KWH), step=100000.0, key="p_elec",
                               help="Albion College news article, Dec 18, 2020: 'about 14 million kilowatt hours'.")
        modeled_share = st.slider("Share of that electricity used by the modeled buildings", 30, 100, 100, key="p_share") / 100
        heat_total = st.number_input("Campus heating fuel (MMBtu/yr), 0 = unknown", value=0.0, step=1000.0, key="p_heat",
                                     help="Leave at 0 to show heating as shares. Enter a number only from a public source you have verified.")
        heating_fraction = st.slider("Weather-driven share of heating fuel", 0, 100, 80, key="p_hfrac") / 100
        var_share = st.slider("Electricity that follows class activity", 0, 60, 30, key="p_var") / 100
        classroom_area = st.slider("Typical classroom area (m2) - assumption", 30, 150, 60, key="p_area")
        room_use_share = st.slider("Room estimate weighted by scheduled hours", 0, 100, 50, key="p_roomuse") / 100
    overrides: tuple = ()
    if scheduled_buildings:
        with st.sidebar.expander("Classroom size and intensity by building", expanded=False):
            st.caption("Classrooms differ between buildings (size, labs, ventilation), and no public room data exists. "
                       "Edit a building's typical classroom area (m2) and an intensity multiplier (1.0 = average). "
                       "Leave the area blank to use the general assumption above.")
            if "room_cfg" not in st.session_state or set(st.session_state.room_cfg["Building"]) != set(scheduled_buildings):
                st.session_state.room_cfg = pd.DataFrame({
                    "Building": sorted(scheduled_buildings),
                    "Classroom area (m2)": [None] * len(scheduled_buildings),
                    "Intensity multiplier": 1.0})
            cfg = st.data_editor(
                st.session_state.room_cfg, hide_index=True, disabled=["Building"], key="room_cfg_editor",
                column_config={
                    "Classroom area (m2)": st.column_config.NumberColumn(min_value=10.0, max_value=400.0, step=5.0),
                    "Intensity multiplier": st.column_config.NumberColumn(min_value=0.2, max_value=5.0, step=0.1)})
            st.session_state.room_cfg = cfg
            overrides = tuple(
                (str(r["Building"]),
                 float(classroom_area) if pd.isna(r["Classroom area (m2)"]) else float(r["Classroom area (m2)"]),
                 1.0 if pd.isna(r["Intensity multiplier"]) else float(r["Intensity multiplier"]))
                for _, r in cfg.iterrows())
    return (elec, modeled_share, heat_total, heating_fraction, var_share, float(classroom_area), room_use_share, overrides)


def render_details(buildings: pd.DataFrame, schedule: pd.DataFrame, data_key: str, params: tuple,
                   focus: str | None = None) -> None:
    """Year / month / room detail that sits under the main map (same page, same assumptions)."""
    st.subheader("Energy details (modeled)")
    st.warning(
        "These are **modeled estimates, not meter readings**. The only public campus-wide figure we could verify is "
        "Albion's electricity use (about 14 million kWh, from a 2020 college news article). Building and room values are "
        "allocations of that total, and heating is shown as shares because no public heating total was found. "
        "See the sources panel below.")
    p = en.Params(*params)
    model, mm, rooms = _compute(buildings, schedule, data_key, params)
    rel = p.heat_is_relative

    c1, c2, c3 = st.columns([2, 2, 2])
    metric = c1.radio("Show", ["Electricity (kWh)", "Heating fuel"], horizontal=True, key="ed_metric")
    period = c2.selectbox("Period", ["Whole year", "Winter (Dec-Feb)"] + en.MONTHS, key="ed_period")
    per_m2 = c3.checkbox("Per square metre", False, key="ed_perm2")

    is_elec = metric.startswith("Elec")
    col = "elec_kwh" if is_elec else "heat"
    scale = 1.0 if is_elec else (100.0 if rel else 1.0)
    unit = "kWh" if is_elec else ("% of annual campus heating" if rel else "MMBtu")
    if period == "Whole year":
        sel = mm
    elif period.startswith("Winter"):
        sel = mm[mm["month"].isin([12, 1, 2])]
    else:
        sel = mm[mm["month_name"] == period]
    val = sel.groupby("name")[col].sum().mul(scale).rename("value").reset_index().merge(
        model[["name", "area_m2", "floors", "class_hours_week", "rooms", "elec_kwh_year", "heat_year"]], on="name")
    if per_m2:
        val["value"] = val["value"] / val["area_m2"].clip(lower=1.0)

    campus_total = float(sel[col].sum()) * scale
    area_m2 = float(model["area_m2"].sum())
    intensity = p.elec_kwh_total * p.modeled_share / (area_m2 / en.FT2_TO_M2)
    k1, k2, k3 = st.columns(3)
    k1.metric(f"Modeled campus total ({period.lower()})",
              f"{campus_total:,.1f} {unit}" if (not is_elec and rel) else f"{campus_total:,.0f} {unit}")
    k2.metric("Modeled floor area (estimate)", f"{area_m2:,.0f} m2", f"{len(model)} buildings", delta_color="off")
    if period.startswith("Winter") and not is_elec:
        full = float(mm[col].sum())
        k3.metric("Share of annual heating fuel in Dec-Feb", f"{campus_total / (full * scale):.0%}")
    else:
        k3.metric("Electricity intensity (modeled)", f"{intensity:.1f} kWh/ft2/yr",
                  "national education average: 9.4 (EIA CBECS 2018)", delta_color="off")

    # ------------------------------------------------------------ charts
    left, right = st.columns(2)
    chart = val.sort_values("value", ascending=False).head(12)
    _ct = en.classroom_table(schedule, rooms, model, p)
    chart = chart.assign(classrooms=chart["name"].map(en.rooms_text(_ct, "building")).fillna("no scheduled classrooms"))
    bars = alt.Chart(chart).mark_bar().encode(
        y=alt.Y("name:N", sort="-x", title=None),
        x=alt.X("value:Q", title=f"{unit}" + (" per m2" if per_m2 else "")),
        tooltip=["name", alt.Tooltip("value:Q", format=",.2f"),
                 alt.Tooltip("classrooms:N", title="Classrooms (credit hours, kWh this term)")])
    left.markdown("**Top buildings**")
    left.altair_chart(bars.properties(height=300), width="stretch")

    names = sorted(model["name"])
    default = focus if focus in names else ("Olin Hall" if "Olin Hall" in names else names[0])
    focus = right.selectbox("Building for monthly view and rooms", names, index=names.index(default))
    one = mm[mm["name"] == focus].assign(v=lambda d: d[col] * scale)
    line = alt.Chart(one).mark_area(opacity=0.4, line=True).encode(
        x=alt.X("month_name:N", sort=en.MONTHS, title=None),
        y=alt.Y("v:Q", title=unit), tooltip=["month_name", alt.Tooltip("v:Q", format=",.2f")])
    right.markdown(f"**{focus}: month by month ({'electricity' if is_elec else 'heating, follows degree days'})**")
    right.altair_chart(line.properties(height=260), width="stretch")

    # ------------------------------------------------------------ tables
    st.markdown("**All modeled buildings**")
    table = model[["name", "floors", "area_m2", "class_hours_week", "rooms", "elec_kwh_year", "heat_year"]].copy()
    winter = mm[mm["month"].isin([12, 1, 2])].groupby("name")["heat"].sum().rename("winter_heat")
    table = table.merge(winter, left_on="name", right_index=True).sort_values("elec_kwh_year", ascending=False)
    bs = en.building_rooms_summary(rooms, model).set_index("building")
    table["classroom_kwh"] = table["name"].map(bs["classroom_kwh_year"]).fillna(0.0)
    table["classroom_share"] = table["name"].map(bs["classroom_share"]).fillna(0.0) * 100
    if rel:
        table["heat_year"] *= 100
        table["winter_heat"] *= 100
        heat_cols = ["Share of annual campus heating, % (est.)", "Share of annual campus heating in Dec-Feb, % (est.)"]
    else:
        heat_cols = ["Heating fuel MMBtu/yr (est.)", "Heating fuel MMBtu Dec-Feb (est.)"]
    table = table[["name", "floors", "area_m2", "class_hours_week", "rooms", "elec_kwh_year", "classroom_kwh",
                   "classroom_share", "heat_year", "winter_heat"]]
    table.columns = ["Building", "Floors (est.)", "Area m2 (est.)", "Class hours/week", "Classrooms in schedule",
                     "Building electricity kWh/yr (est.)", "Classrooms' electricity kWh/yr (sum of rooms, est.)",
                     "Classrooms as % of building"] + heat_cols
    st.dataframe(table.round(2), hide_index=True, height=300)
    st.download_button("Download building estimates (CSV)", table.round(2).to_csv(index=False).encode("utf-8"),
                       "albion_building_energy_estimates.csv", "text/csv")

    rr = rooms[rooms["building"] == focus]
    st.markdown(f"**Rooms in {focus}** (building electricity per m2 x a typical classroom area, weighted by use; relative, modeled)")
    if rr.empty:
        st.caption("This building has no rooms in the schedule, so no room estimate is possible.")
    else:
        show = rr[["room", "class_hours_week", "meetings", "elec_kwh_year_room"]].copy()
        show.columns = ["Room", "Class hours/week", "Meetings/week", "Electricity kWh/yr (est.)"]
        st.dataframe(show.round(1), hide_index=True, height=240)
        st.download_button("Download all room estimates (CSV)", rooms.round(1).to_csv(index=False).encode("utf-8"),
                           "albion_room_energy_estimates.csv", "text/csv")

    # ------------------------------------------------------------ classrooms in use, per term
    use = en.room_use(schedule, rooms, p)
    days = en.term_days_per_weekday()
    st.markdown("**Classrooms in use: electricity while classes run (Fall 2026 term, modeled)**")
    u1, u2, u3 = st.columns(3)
    u1.metric("Class hours in the term (all rooms)", f"{use['class_hours_term'].sum():,.0f} h")
    u2.metric("Electricity drawn while classes run", f"{use['kwh_in_use_term'].sum():,.0f} kWh")
    u3.metric("Added by class activity (above constant load)", f"{use['kwh_extra_term'].sum():,.0f} kWh")
    st.caption(
        "Class days counted from the [Registrar's academic calendar](https://www.albion.edu/offices/registrar/academic-calendar/): "
        f"classes Aug 24 to Dec 4, no classes Sep 7, Oct 12-13 and Nov 25-28 ("
        + ", ".join(f"{k} x{v}" for k, v in days.items()) + "). Final exams are not counted.")
    ub = use[use["building"] == focus]
    show_u = (ub if not ub.empty else use.head(25))[["building", "room", "sessions_term", "class_hours_term",
                                                       "kw_in_use", "kwh_in_use_term", "kwh_extra_term"]].copy()
    show_u.columns = ["Building", "Room", "Class meetings in term", "Class hours in term", "Demand while in use (kW)",
                      "Electricity while in use (kWh/term)", "Added by class activity (kWh/term)"]
    st.dataframe(show_u.round(1), hide_index=True, height=260)
    st.caption(f"Showing {'rooms in ' + focus if not ub.empty else 'the 25 rooms with the most use'}. "
               "Values are modeled allocations of Albion's campus electricity, not meter readings.")
    st.download_button("Download classroom-use estimates (CSV)", use.round(1).to_csv(index=False).encode("utf-8"),
                       "albion_classroom_use_energy_fall2026.csv", "text/csv")
