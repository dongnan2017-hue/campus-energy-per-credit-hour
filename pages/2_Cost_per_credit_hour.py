"""Third page: energy cost per credit hour for Fall 2026 (modeled), built from classroom energy cost."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import campus_data as cd
import common
import energy as en
import energy_view


buildings, schedule, data_key = common.load()
params = energy_view.sidebar_params(sorted(schedule["building"].unique()))
p = en.Params(*params)

st.sidebar.markdown("**Prices and method**")
price_c = st.sidebar.number_input(
    "Electricity price (cents/kWh)", min_value=0.0, value=14.01, step=0.1, key="price_elec",
    help="Default: Michigan commercial average for 2024 from the U.S. EIA. Albion's actual rate is not public.")
st.sidebar.caption("Energy counted: only the electricity of the classrooms teaching students, while their classes run. "
                   "Offices, hallways and the rest of each building are not charged to credit hours.")
mode = "in_use"
mode_label = "Classroom electricity while classes run"
other_c = st.sidebar.number_input(
    "Your other cost per credit hour ($), optional", min_value=0.0, value=0.0, step=10.0, key="other_cost",
    help="Enter a figure you already have (for example instruction cost per credit hour). The page adds the energy "
         "cost to it. Nothing is assumed if you leave it at 0.")
price = price_c / 100.0

st.title("Energy cost per credit hour, Fall 2026 (modeled)")
st.warning(
    "**Modeled estimates, not utility bills.** Albion's only verified public energy figure is its electricity use (about 14 million kWh). "
    "Room, course and credit-hour costs are allocations of that total at the price in the sidebar. "
    "Credit hours use Albion's rule that 1 unit = 4 semester hours (Registrar FAQ).")

model, mm, rooms = energy_view._compute(buildings, schedule, data_key, params)
meetings = en.course_energy(schedule, rooms, model, p, mode)
sections = en.sections_from(meetings)
campus = en.rollup(sections, price, None, other_c).iloc[0]
dept_names = sections.drop_duplicates("dept").set_index("dept")["dept_name"].fillna("").to_dict()
dept_label = lambda d: d  # the department label is the group name

# ------------------------------------------------------------ headline
use = en.room_use(schedule, rooms, p)
room_cost_total = float(use["kwh_in_use_term"].sum()) * price
k1, k2, k3, k4 = st.columns(4)
k1.metric("Classroom energy cost, Fall 2026 classes", f"${room_cost_total:,.0f}",
          f"{use['class_hours_term'].sum():,.0f} class hours in {len(use)} rooms", delta_color="off")
k2.metric("Energy cost per student credit hour", f"${campus['energy_per_student_credit_hour']:,.2f}",
          f"{campus['student_credit_hours']:,.0f} student credit hours", delta_color="off")
k3.metric("Energy cost per credit hour offered", f"${campus['energy_per_credit_hour']:,.2f}",
          f"{campus['credit_hours']:,.0f} credit hours in {int(campus['sections'])} sections", delta_color="off")
if other_c > 0:
    k4.metric("With your other cost added (per credit hour)", f"${campus['total_per_credit_hour']:,.2f}",
              f"energy is {campus['energy_per_credit_hour'] / campus['total_per_credit_hour']:.1%} of it", delta_color="off")
else:
    k4.metric("Energy counted", "Classrooms only", "while classes run", delta_color="off")
st.caption(
    "**Credit hours offered** counts each section's credit hours once. **Student credit hours** multiply each section's credit hours by its "
    "seat count (aggregate enrollment shown in Albion's public course search; no student information is used). Lab sections with no "
    "credit keep their energy in the course they belong to.")

# ------------------------------------------------------------ departments
st.subheader("Energy cost per credit hour, by department")
st.caption("Departments are the Registrar's subject names for each section.")
dept = en.rollup(sections, price, "dept", other_c).rename(columns={"group": "dept"})
dept["name"] = dept["dept"].map(dept_names)
dept["department"] = dept["dept"].map(dept_label)
metric = st.radio("Rank departments by", ["Energy cost per student credit hour", "Energy cost per credit hour offered", "Total energy cost"],
                  horizontal=True)
col = {"Energy cost per credit hour offered": "energy_per_credit_hour",
       "Energy cost per student credit hour": "energy_per_student_credit_hour", "Total energy cost": "energy_cost"}[metric]
camp_val = float({"energy_per_credit_hour": campus["energy_per_credit_hour"],
                  "energy_per_student_credit_hour": campus["energy_per_student_credit_hour"],
                  "energy_cost": dept["energy_cost"].mean()}[col])
dchart = dept.dropna(subset=[col]).sort_values(col, ascending=False)
dchart = dchart.assign(classrooms=dchart["dept"].map(en.dept_rooms_text(meetings, price)).fillna(""),
                       vs_campus=dchart[col] / max(camp_val, 1e-9))
axis_title = metric + " ($)"
bars = alt.Chart(dchart).mark_bar().encode(
    y=alt.Y("department:N", sort="-x", title=None), x=alt.X(f"{col}:Q", title=axis_title),
    color=alt.condition(alt.datum[col] > camp_val, alt.value("#e8743b"), alt.value("#3b82c4")),
    tooltip=[alt.Tooltip("department:N", title="Department"),
             alt.Tooltip("energy_per_credit_hour:Q", title="Energy $ per credit hour", format="$,.2f"),
             alt.Tooltip("energy_per_student_credit_hour:Q", title="Energy $ per student credit hour", format="$,.2f"),
             alt.Tooltip("energy_cost:Q", title="Total energy cost", format="$,.0f"),
             alt.Tooltip("credit_hours:Q", title="Credit hours offered", format=",.0f"),
             alt.Tooltip("sections:Q", title="Sections"),
             alt.Tooltip("vs_campus:Q", title="Times the campus average", format=".2f"),
             alt.Tooltip("classrooms:N", title="Classrooms used (credit hours, kWh, cost)")])
avg_rule = alt.Chart(pd.DataFrame({"v": [camp_val]})).mark_rule(color="#888", strokeDash=[5, 4], size=2).encode(x="v:Q")
st.altair_chart((bars + avg_rule).properties(height=max(260, 20 * len(dchart))), width="stretch")
st.caption(f"Dashed line = campus average (${camp_val:,.2f}). Orange bars are above it, blue bars below. "
           "Hover a bar for credit hours and the classrooms the department uses.")
dt = dept[["dept", "sections", "class_hours_term", "kwh", "energy_cost", "credit_hours", "student_credit_hours",
           "energy_per_credit_hour", "energy_per_student_credit_hour"]].copy()
dt["vs_campus"] = dept["energy_per_credit_hour"] / max(float(campus["energy_per_credit_hour"]), 1e-9)
dt.columns = ["Department", "Sections", "Class hours (term)", "Electricity kWh", "Energy cost $", "Credit hours offered",
              "Student credit hours", "Energy $ per credit hour", "Energy $ per student credit hour", "x campus average ($ per credit hour)"]
st.dataframe(dt.sort_values("Energy $ per credit hour", ascending=False, na_position="last").round(2), hide_index=True,
             height=min(560, 36 * (len(dt) + 1)))
nocr = dt[dt["Credit hours offered"] <= 0]["Department"].tolist()
if nocr:
    st.caption("No credit hours in the schedule (their classroom energy has no credit hours to divide by): " + ", ".join(nocr) + ".")
st.download_button("Download department costs (CSV)", dt.round(2).to_csv(index=False).encode("utf-8"),
                   "albion_fall2026_energy_cost_by_department.csv", "text/csv")

# ------------------------------------------------------------ courses and sections
st.markdown("**Courses and sections**")
pick = st.selectbox("Department", ["(all)"] + sorted(sections["dept"].unique()),
                    format_func=lambda d: d if d == "(all)" else dept_label(d))
sec = sections if pick == "(all)" else sections[sections["dept"] == pick]
course = en.rollup(sec, price, "course_code", other_c).rename(columns={"group": "course_code"})
_titles = sections.drop_duplicates("course_code").set_index("course_code")["course_title"]
course["title"] = course["course_code"].map(_titles)
ct = course[["course_code", "title", "sections", "class_hours_term", "kwh", "energy_cost", "credit_hours", "student_credit_hours",
             "energy_per_credit_hour", "energy_per_student_credit_hour"]].copy()
ct.columns = ["Course", "Title", "Sections", "Class hours (term)", "Electricity kWh", "Energy cost $", "Credit hours offered",
              "Student credit hours", "Energy $ per credit hour", "Energy $ per student credit hour"]
st.dataframe(ct.sort_values("Energy cost $", ascending=False).round(2), hide_index=True, height=300)
sx = sec.assign(cost=sec["kwh"] * price)
sx["per_credit_hour"] = sx["cost"] / sx["credit_hours"].replace(0, float("nan"))
sx["per_sch"] = sx["cost"] / sx["student_credit_hours"].replace(0, float("nan"))
st3 = sx[["crn", "course_code", "section", "course_title", "buildings", "class_hours_term", "kwh", "cost", "credit_hours", "enrollment", "per_credit_hour", "per_sch"]].copy()
st3.columns = ["CRN", "Course", "Section", "Title", "Building(s)", "Class hours (term)", "kWh", "Energy cost $", "Credit hours", "Seats", "Energy $ per credit hour",
               "Energy $ per student credit hour"]
with st.expander("Every section"):
    st.dataframe(st3.sort_values("Energy cost $", ascending=False).round(2), hide_index=True, height=360)
st.download_button("Download section costs (CSV)", st3.round(2).to_csv(index=False).encode("utf-8"),
                   "albion_fall2026_energy_cost_by_section.csv", "text/csv")
unmodeled = int(sections["unmodeled_rows"].sum())
if unmodeled:
    st.caption(f"{unmodeled} class meeting(s) are in buildings that are not on the map (for example Dow and Serra fitness centers), "
               "so they carry no energy cost here.")

# ------------------------------------------------------------ department detail
st.markdown("**Department detail: which rooms and buildings each department's classes use**")
dsel = st.selectbox("Department detail", sorted(dept_names), format_func=dept_label, key="dept_detail",
                    index=sorted(dept_names).index("Biology") if "Biology" in dept_names else 0)
dm = meetings[meetings["dept"] == dsel].copy()
dsec = sections[sections["dept"] == dsel]
drow = dept[dept["dept"] == dsel].iloc[0]
d1, d2, d3, d4 = st.columns(4)
d1.metric(f"{dept_names.get(dsel, dsel)}: classroom energy cost", f"${drow['energy_cost']:,.0f}",
          f"{int(drow['sections'])} sections, {drow['class_hours_term']:,.0f} class hours", delta_color="off")
d2.metric("Credit hours offered", f"{drow['credit_hours']:,.0f}")
d3.metric("Energy per credit hour", f"${drow['energy_per_credit_hour']:,.2f}" if pd.notna(drow["energy_per_credit_hour"]) else "-")
d4.metric("Energy per student credit hour",
          f"${drow['energy_per_student_credit_hour']:,.2f}" if pd.notna(drow["energy_per_student_credit_hour"]) else "-")
_sec_hours = dm.groupby("crn")["hours_term"].transform("sum").clip(lower=1e-9)
dm["credit_share"] = dm["credit_hours"].fillna(0.0) * dm["hours_term"] / _sec_hours
droom = dm.groupby(["building", "room"]).agg(sections=("crn", "nunique"), credit_hours=("credit_share", "sum"),
                                              class_hours=("hours_term", "sum"), kwh=("kwh", "sum")).reset_index()
droom["cost"] = droom["kwh"] * price
dbld = droom.groupby("building").agg(rooms=("room", "count"), credit_hours=("credit_hours", "sum"), kwh=("kwh", "sum"),
                                     cost=("cost", "sum")).reset_index()
dl, dr = st.columns([2, 3])
dchart2 = alt.Chart(dbld).mark_bar().encode(
    y=alt.Y("building:N", sort="-x", title=None), x=alt.X("cost:Q", title="Classroom energy cost ($)"),
    tooltip=["building", "rooms", alt.Tooltip("credit_hours:Q", format=",.1f"), alt.Tooltip("kwh:Q", format=",.0f"),
             alt.Tooltip("cost:Q", format="$,.0f")])
dl.altair_chart(dchart2.properties(height=max(120, 34 * len(dbld))), width="stretch")
dshow = droom.sort_values("cost", ascending=False)[["building", "room", "sections", "credit_hours", "class_hours", "kwh", "cost"]]
dshow.columns = ["Building", "Room", "Sections", "Credit hours", "Class hours", "Electricity kWh", "Energy cost $"]
dr.dataframe(dshow.round(2), hide_index=True, height=max(160, 34 * min(len(dshow), 9)))
st.caption("A section's credit hours are shared over the rooms it meets in, by class hours. Modeled, not metered.")

# ------------------------------------------------------------ how classrooms differ between buildings
st.markdown("**How classroom energy cost differs between buildings**")
rb = use.assign(cost_per_class_hour=use["kw_in_use"] * price, cost_in_use=use["kwh_in_use_term"] * price)
vb = rb.groupby("building").agg(
    rooms=("room", "count"), class_hours=("class_hours_term", "sum"),
    cost_per_class_hour_avg=("cost_per_class_hour", "mean"), cost_per_class_hour_min=("cost_per_class_hour", "min"),
    cost_per_class_hour_max=("cost_per_class_hour", "max"), cost_term=("cost_in_use", "sum")).reset_index()
vb["cost_per_room"] = vb["cost_term"] / vb["rooms"].clip(lower=1)
ctab = en.classroom_table(schedule, rooms, model, p, price)
vb["classrooms"] = vb["building"].map(en.rooms_text(ctab, "building", price=price)).fillna("")
_bs = en.building_rooms_summary(rooms, model).set_index("building")
vb["classroom_kwh_year"] = vb["building"].map(_bs["classroom_kwh_year"])
vb["classroom_share"] = vb["building"].map(_bs["classroom_share"]) * 100
vleft, vright = st.columns([3, 2])
rng = alt.Chart(vb).mark_rule(strokeWidth=3).encode(
    y=alt.Y("building:N", sort="-x", title=None),
    x=alt.X("cost_per_class_hour_min:Q", title="Classroom electricity cost per class hour ($)"), x2="cost_per_class_hour_max:Q")
dots = alt.Chart(vb).mark_point(filled=True, size=90).encode(
    y=alt.Y("building:N", sort="-x"), x="cost_per_class_hour_avg:Q",
    tooltip=["building", "rooms", alt.Tooltip("classrooms:N", title="Classrooms (credit hours, kWh, cost)"),
             alt.Tooltip("cost_per_class_hour_avg:Q", format="$,.2f"),
             alt.Tooltip("cost_per_class_hour_min:Q", format="$,.2f"), alt.Tooltip("cost_per_class_hour_max:Q", format="$,.2f")])
vleft.altair_chart((rng + dots).properties(height=max(240, 26 * len(vb))), width="stretch")
vt = vb[["building", "rooms", "class_hours", "classroom_kwh_year", "classroom_share", "cost_per_class_hour_avg",
         "cost_per_class_hour_min", "cost_per_class_hour_max", "cost_per_room", "cost_term"]].copy()
vt.columns = ["Building", "Classrooms", "Class hours", "Classroom electricity kWh/yr", "% of building", "Avg $ per class hour",
              "Lowest room $", "Highest room $", "Cost per room (term) $", "Building classroom cost (term) $"]
vright.dataframe(vt.sort_values("Avg $ per class hour", ascending=False).round(2), hide_index=True, height=max(240, 26 * len(vb)))
st.caption("Dot = average of the building's rooms, line = lowest to highest room. Differences come from the building's electricity "
           "per m2, its classroom area and intensity multiplier (edit them in the sidebar under *Classroom size and intensity by "
           "building*), and how much each room is scheduled. These are not measured differences.")

# ------------------------------------------------------------ every classroom: credit hours vs energy
st.markdown("**Every classroom: credit hours taught and electricity while classes run**")
cs = ctab.copy()
cs["label"] = cs["building"] + " " + cs["room"]
dots = alt.Chart(cs).mark_circle(size=90, opacity=0.8).encode(
    x=alt.X("credit_hours:Q", title="Credit hours taught in the room (Fall 2026)"),
    y=alt.Y("kwh_in_use_term:Q", title="Electricity while classes run (kWh)"),
    color=alt.Color("building:N", legend=None),
    tooltip=[alt.Tooltip("label:N", title="Classroom"), alt.Tooltip("sections:Q", title="Sections"),
             alt.Tooltip("credit_hours:Q", title="Credit hours", format=",.1f"),
             alt.Tooltip("class_hours_term:Q", title="Class hours", format=",.0f"),
             alt.Tooltip("kw_in_use:Q", title="Demand while in use (kW)", format=",.1f"),
             alt.Tooltip("kwh_in_use_term:Q", title="Electricity (kWh)", format=",.0f"),
             alt.Tooltip("cost_in_use:Q", title="Cost ($)", format="$,.0f"),
             alt.Tooltip("cost_per_credit_hour:Q", title="Cost per credit hour ($)", format="$,.2f")])
st.altair_chart(dots.properties(height=340).interactive(), width="stretch")
st.caption("One dot per classroom. A section's credit hours are shared over the rooms it meets in, by class hours. "
           "Modeled estimates, not meter readings.")

# ------------------------------------------------------------ classroom energy cost (the building block)
st.markdown("**Classroom energy cost (the building block)**")
cr = use.assign(cost_in_use=use["kwh_in_use_term"] * price, cost_per_class_hour=use["kw_in_use"] * price)
cc = cr[["building", "room", "class_hours_term", "kw_in_use", "kwh_in_use_term", "cost_in_use", "cost_per_class_hour"]].head(30).copy()
cc.columns = ["Building", "Room", "Class hours (term)", "Demand while in use (kW)", "kWh while in use", "Cost while in use $",
              "Cost per class hour $"]
st.dataframe(cc.round(2), hide_index=True, height=300)
st.caption("The 30 rooms with the highest cost. A room = its building's electricity per m2 x a typical classroom area "
           "(assumption, adjustable in the sidebar), weighted by how much it is scheduled. Class days from the "
           "[Registrar's academic calendar](https://www.albion.edu/offices/registrar/academic-calendar/).")

energy_view.sources_panel()
st.caption("Unofficial student project; not affiliated with or endorsed by Albion College.")
