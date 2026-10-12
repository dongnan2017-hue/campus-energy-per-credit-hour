"""Second page: modeled energy cost for the Fall 2026 term (electricity, plus heating if a total and price are entered)."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import common
import energy as en
import energy_view


buildings, schedule, data_key = common.load()
params = energy_view.sidebar_params(sorted(schedule["building"].unique()))
p = en.Params(*params)

st.sidebar.markdown("**Prices**")
price_c = st.sidebar.number_input(
    "Electricity price (cents/kWh)", min_value=0.0, value=14.01, step=0.1, key="price_elec",
    help="Default: Michigan commercial average for 2024 from the U.S. EIA (14.01 cents/kWh). "
         "Albion's actual supplier rate is not public and may differ. Enter your own if you know it.")
gas_price = st.sidebar.number_input(
    "Heating fuel price ($/MMBtu), optional", min_value=0.0, value=0.0, step=0.5, key="price_gas",
    help="Heating cost is only shown when you also enter a campus heating total (MMBtu/yr) under Energy assumptions. "
         "No public Albion heating total or fuel price was found.")
period_name = st.sidebar.radio(
    "Fall 2026 period", ["Whole term incl. finals (Aug 24 - Dec 10)", "Classes only (Aug 24 - Dec 4)"], index=0)
end = en.FALL_EXAMS_END if period_name.startswith("Whole") else en.FALL_CLASSES_END
price = price_c / 100.0  # $/kWh

st.title("Energy cost, Fall 2026 (modeled)")
st.warning(
    "These are **modeled estimates, not utility bills**. Albion's only verified public energy figure is its electricity use "
    "(about 14 million kWh, from a 2020 college news article). Building and room costs are allocations of that total at the "
    "price in the sidebar. See the sources panel at the bottom.")

model, mm, rooms = energy_view._compute(buildings, schedule, data_key, params)
w = en.period_weights(p, en.FALL_START, end)
elec_frac = float(w["elec_frac"].sum())
heat_frac = float(w["heat_frac"].sum())
days = int(w["days"].sum())

campus_kwh_year = float(model["elec_kwh_year"].sum())
period_kwh = campus_kwh_year * elec_frac
period_cost = period_kwh * price

# ------------------------------------------------------------ headline numbers
k1, k2, k3, k4 = st.columns(4)
k1.metric("Electricity cost, Fall 2026 (modeled)", f"${period_cost:,.0f}")
k2.metric("Electricity used in the period", f"{period_kwh:,.0f} kWh", f"{days} days, {elec_frac:.0%} of the year", delta_color="off")
k3.metric("Average per day", f"${period_cost / max(days, 1):,.0f}")
if p.heat_total_mmbtu > 0 and gas_price > 0:
    heat_mmbtu = p.heat_total_mmbtu * heat_frac * p.modeled_share
    k4.metric("Heating cost, Fall 2026 (modeled)", f"${heat_mmbtu * gas_price:,.0f}",
              f"{heat_mmbtu:,.0f} MMBtu ({heat_frac:.0%} of annual)", delta_color="off")
else:
    k4.metric("Share of annual heating fuel used", f"{heat_frac:.0%}",
              "enter a heating total and price for dollars", delta_color="off")

# ------------------------------------------------------------ month by month
st.markdown("**Cost by month**")
wm = w.copy()
wm["kwh"] = campus_kwh_year * wm["elec_frac"]
wm["cost"] = wm["kwh"] * price
bars = alt.Chart(wm).mark_bar().encode(
    x=alt.X("month_name:N", sort=list(wm["month_name"]), title=None),
    y=alt.Y("cost:Q", title="Electricity cost ($)"),
    tooltip=["month_name", alt.Tooltip("days:Q", title="days in period"), alt.Tooltip("kwh:Q", format=",.0f"),
             alt.Tooltip("cost:Q", format="$,.0f")])
st.altair_chart(bars.properties(height=230), width="stretch")
st.caption("August and December are partial months. Electricity is spread evenly over days; heating follows the "
           "[NOAA heating degree-day normals](https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals).")

# ------------------------------------------------------------ buildings
st.markdown("**Cost by building**")
b = model[["name", "floors", "area_m2", "elec_kwh_year"]].copy()
b["kwh_period"] = b["elec_kwh_year"] * elec_frac
b["cost_period"] = b["kwh_period"] * price
b["share"] = b["cost_period"] / max(b["cost_period"].sum(), 1e-9)
b = b.sort_values("cost_period", ascending=False)
_ct = en.classroom_table(schedule, rooms, model, p, price)
b["classrooms"] = b["name"].map(en.rooms_text(_ct, "building", price=price)).fillna("no scheduled classrooms")
left, right = st.columns([3, 2])
top = alt.Chart(b.head(15)).mark_bar().encode(
    y=alt.Y("name:N", sort="-x", title=None), x=alt.X("cost_period:Q", title="Fall 2026 electricity cost ($)"),
    tooltip=["name", alt.Tooltip("cost_period:Q", format="$,.0f"), alt.Tooltip("kwh_period:Q", format=",.0f"),
             alt.Tooltip("classrooms:N", title="Classrooms (credit hours, kWh this term, cost)")])
left.altair_chart(top.properties(height=380), width="stretch")
tb = b[["name", "floors", "area_m2", "kwh_period", "cost_period", "share"]].copy()
tb.columns = ["Building", "Floors (est.)", "Area m2 (est.)", "Electricity kWh (est.)", "Cost $ (est.)", "Share of modeled cost"]
right.dataframe(tb.round(2), hide_index=True, height=380,
                column_config={"Share of modeled cost": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=float(tb["Share of modeled cost"].max()) or 1.0)})
st.download_button("Download building costs (CSV)", tb.round(2).to_csv(index=False).encode("utf-8"),
                   "albion_fall2026_building_energy_cost.csv", "text/csv")

# ------------------------------------------------------------ classrooms
use = en.room_use(schedule, rooms, p)
use["cost_in_use"] = use["kwh_in_use_term"] * price
use["cost_extra"] = use["kwh_extra_term"] * price
use["cost_per_class_hour"] = use["kw_in_use"] * price
st.markdown("**Classrooms in use: electricity cost while classes run (class days only)**")
c1, c2, c3 = st.columns(3)
c1.metric("Class hours in the term", f"{use['class_hours_term'].sum():,.0f} h")
c2.metric("Cost while classes run", f"${use['cost_in_use'].sum():,.0f}")
c3.metric("Average cost per class hour", f"${use['cost_in_use'].sum() / max(use['class_hours_term'].sum(), 1):,.2f}")
names = sorted(use["building"].unique())
pick = st.selectbox("Building", ["(all, top 30 rooms)"] + names)
shown = use.head(30) if pick.startswith("(all") else use[use["building"] == pick]
sc = shown[["building", "room", "sessions_term", "class_hours_term", "kw_in_use", "kwh_in_use_term", "cost_in_use",
            "cost_per_class_hour"]].copy()
sc.columns = ["Building", "Room", "Class meetings", "Class hours", "Demand in use (kW)", "Electricity in use (kWh)",
              "Cost while in use ($)", "Cost per class hour ($)"]
st.dataframe(sc.round(2), hide_index=True, height=320)
st.caption("Each room = its building's electricity per m2 x a typical classroom area (assumption, adjustable in the sidebar), "
           "weighted by how much it is scheduled; the cost is what it draws while a class runs. Class days are counted from the "
           "[Registrar's academic calendar](https://www.albion.edu/offices/registrar/academic-calendar/). Not a bill.")
st.download_button("Download classroom costs (CSV)", use.round(2).to_csv(index=False).encode("utf-8"),
                   "albion_fall2026_classroom_energy_cost.csv", "text/csv")

energy_view.sources_panel()
st.caption("Unofficial student project; not affiliated with or endorsed by Albion College.")
