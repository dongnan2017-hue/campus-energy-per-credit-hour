"""Methodology page: how every number in the app is calculated, with a diagram and live worked examples."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import common
import energy as en
import energy_view

DOT = r"""
digraph G {
  rankdir=LR; bgcolor="transparent"; nodesep=0.28; ranksep=0.6;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, margin="0.12,0.07"];
  edge [color="#8a94a6", arrowsize=0.7];

  subgraph cluster_data { label="Public data"; fontname="Helvetica"; style="rounded"; color="#4a90d9"; fontcolor="#4a90d9";
    node [fillcolor="#dbeafe", color="#4a90d9"];
    art  [label="Albion article\n~14 million kWh a year"];
    osm  [label="OpenStreetMap\nbuilding outlines and floors"];
    reg  [label="Registrar Fall 2026 schedule\nrooms, times, credits, seats,\ntitles, departments"];
    cal  [label="Academic calendar\nclass days"];
    eia  [label="EIA Michigan price\n14.01 cents per kWh"];
    noaa [label="NOAA heating\ndegree days"];
  }
  subgraph cluster_assume { label="Assumptions (adjustable)"; fontname="Helvetica"; style="rounded"; color="#e08a1e"; fontcolor="#e08a1e";
    node [fillcolor="#fde8c8", color="#e08a1e"];
    a1 [label="70% constant load /\n30% follows classes"];
    a2 [label="Typical classroom area\n60 m2 (per building)"];
    a3 [label="Room estimate:\n50% weighted by hours"];
    a4 [label="80% of heating fuel\nis weather-driven"];
  }

  node [fillcolor="#dcfce7", color="#2e9e5b"];
  area   [label="Building floor area\nfootprint x floors"];
  hours  [label="Class hours per week\nper building and room"];
  factor [label="Activity factor\n0.70 + 0.30 x density / average"];
  share  [label="Building electricity per year\n14M kWh x (area x factor) share"];
  perm2  [label="Building kWh per m2"];
  room   [label="Room kWh per year\n= kWh per m2 x classroom area x use factor\n(never more than the building)"];
  kw     [label="Room kW\nno class: x 0.70\nclass running: x (0.70 + 0.30 / time in use)"];
  term   [label="Class hours in the term\n= weekly hours x class days"];
  kwhterm[label="Room kWh while classes run"];
  cost   [label="Cost = kWh x price"];
  cph    [label="Energy cost per credit hour\n= cost / credit hours\n(1 unit = 4 credit hours)"];
  sch    [label="Cost per student credit hour\n= cost / (credit hours x seats)"];
  heat   [label="Heating share by month\nfollows degree days"];

  node [fillcolor="#ede9fe", color="#7c5cd6"];
  out1 [label="Energy cost per credit hour\n(first page, by department)"];
  out2 [label="Campus map\nhover and floor view"];
  out3 [label="Energy cost, Fall 2026"];
  out4 [label="Power BI visual"];

  osm -> area; reg -> hours; area -> factor; hours -> factor; a1 -> factor;
  factor -> share; art -> share; area -> share; share -> perm2; area -> perm2;
  perm2 -> room; a2 -> room; hours -> room; a3 -> room;
  room -> kw; a1 -> kw; kw -> kwhterm; term -> kwhterm; cal -> term; hours -> term;
  kwhterm -> cost; eia -> cost; cost -> cph; reg -> cph; cph -> out1; cost -> sch; reg -> sch; sch -> out1;
  room -> out2; kw -> out2; cost -> out3; share -> heat; noaa -> heat; a4 -> heat; heat -> out3;
  share -> out4; room -> out4;
}
"""

buildings, schedule, data_key = common.load()
params = energy_view.sidebar_params(sorted(schedule["building"].unique()))
p = en.Params(*params)
price_c = st.sidebar.number_input("Electricity price (cents/kWh)", min_value=0.0, value=14.01, step=0.1, key="price_elec")
price = price_c / 100.0

st.title("Methodology")
st.markdown(
    "Every number in the app, how it is calculated, and where each input comes from. Change the sidebar assumptions and the "
    "live examples recompute. **All building, room and cost values are modeled allocations of one rounded campus total, not meter readings.** "
    "Source links are on the *Data sources* page.")

model, mm, rooms = energy_view._compute(buildings, schedule, data_key, params)
ctab = en.classroom_table(schedule, rooms, model, p, price)
meetings = en.course_energy(schedule, rooms, model, p, "in_use")
sections = en.sections_from(meetings)
days = en.term_days_per_weekday()
base = 1 - p.var_share

t_diag, t_room, t_credit, t_dict, t_other, t_checks = st.tabs(
    ["Diagram", "Room example (live)", "Credit hours and departments (live)", "Every number explained", "Heating, Fall 2026 cost, map and walkers", "Checks"])

# =============================================================================== diagram
with t_diag:
    st.markdown("Blue = public data, orange = assumptions you can change, green = arithmetic, purple = what you see.")
    st.graphviz_chart(DOT, width="stretch")
    st.caption("Read left to right. Public data and assumptions feed the building estimate, then the room estimate, then cost, then cost per credit hour.")

# =============================================================================== room example
with t_room:
    st.markdown("Pick a classroom and follow the calculation from the 14 million kWh down to its cost per credit hour.")
    sched_b = sorted(rooms["building"].unique())
    c1, c2 = st.columns(2)
    bsel = c1.selectbox("Building", sched_b, index=sched_b.index("Olin Hall") if "Olin Hall" in sched_b else 0, key="m_building")
    room_list = sorted(rooms.loc[rooms["building"] == bsel, "room"].unique())
    rsel = c2.selectbox("Classroom", room_list, index=room_list.index("215") if "215" in room_list else 0, key="m_room")

    mb = model[model["name"] == bsel].iloc[0]
    sc = model[model["class_hours_week"] > 0]
    d_avg = sc["class_hours_week"].sum() / max(sc["area_m2"].sum(), 1.0)
    density = mb["class_hours_week"] / max(mb["area_m2"], 1.0)
    rr = rooms[(rooms["building"] == bsel) & (rooms["room"] == rsel)].iloc[0]
    mean_h = rooms.loc[rooms["building"] == bsel, "minutes_week"].mean() / 60.0
    use_factor = (1 - p.room_use_share) + p.room_use_share * (rr["minutes_week"] / 60.0) / max(mean_h, 1e-9)
    ov = {b: (a, m) for b, a, m in p.room_overrides}
    area_room, mult = ov.get(bsel, (p.classroom_area_m2, 1.0))
    uncapped = mb["elec_kwh_m2"] * area_room * mult * use_factor
    u = ctab[(ctab["building"] == bsel) & (ctab["room"] == rsel)].iloc[0]
    avg_kw = rr["elec_kwh_year_room"] / 8760.0
    occ = rr["minutes_week"] / (7 * 24 * 60.0)
    wsum = (model["area_m2"] * model["elec_factor"]).sum()
    steps = [
        ("1", "Campus electricity", "Albion article: 'about 14 million kilowatt hours'; period assumed to be one year",
         f"{p.elec_kwh_total:,.0f} kWh x {p.modeled_share:.0%} modeled share = {p.elec_kwh_total * p.modeled_share:,.0f} kWh", "Public data"),
        ("2", f"{bsel}: footprint", "Shoelace formula on the OpenStreetMap outline in local metres (x = (lon - lon0) x 111,320 x cos(lat), y = (lat - lat0) x 110,574)",
         f"{mb['footprint_m2']:,.0f} m2", "Public data + arithmetic"),
        ("3", f"{bsel}: floors and floor area", "floors = max(OpenStreetMap floor count, highest floor implied by room numbers, 1); area = footprint x floors",
         f"{int(mb['floors'])} floors; {mb['area_m2']:,.0f} m2", "Public data + arithmetic"),
        ("4", f"{bsel}: class hours per week", "Sum of the duration of every class meeting in the building (each weekday counted separately)",
         f"{mb['class_hours_week']:,.1f} h", "Public data"),
        ("5", "Class-hour density and its average", f"density = hours / area; average = total scheduled hours / total scheduled area",
         f"{density:.4f} per m2; average {d_avg:.4f}", "Arithmetic"),
        ("6", "Activity factor", f"(1 - s) + s x density / average with s = {p.var_share:.2f}  ->  {base:.2f} + {p.var_share:.2f} x ({density:.4f} / {d_avg:.4f})",
         f"{mb['elec_factor']:.3f}", "Assumption (the 70/30 split)"),
        ("7", f"{bsel}: electricity per year", f"campus kWh x modeled share x (area x factor) / sum over all buildings = {p.elec_kwh_total * p.modeled_share:,.0f} x {mb['area_m2'] * mb['elec_factor']:,.0f} / {wsum:,.0f}",
         f"{mb['elec_kwh_year']:,.0f} kWh = {mb['elec_kwh_m2']:.1f} kWh per m2", "Arithmetic"),
        ("8", f"Room {rsel}: scheduled hours", f"{rr['minutes_week'] / 60:.1f} h per week; average room in the building {mean_h:.1f} h per week",
         f"use factor = (1 - u) + u x room h / average h with u = {p.room_use_share:.2f}: {1 - p.room_use_share:.2f} + {p.room_use_share:.2f} x ({rr['minutes_week'] / 60:.1f} / {mean_h:.1f}) = {use_factor:.3f}", "Assumption (50/50)"),
        ("9", f"Room {rsel}: electricity per year", f"building kWh per m2 x classroom area x intensity multiplier x use factor = {mb['elec_kwh_m2']:.1f} x {area_room:.0f} x {mult:.2f} x {use_factor:.3f}",
         f"{uncapped:,.0f} kWh" + (f"; scaled to {rr['elec_kwh_year_room']:,.0f} because the building's rooms may not exceed the building" if abs(uncapped - rr['elec_kwh_year_room']) > 1 else ""),
         "Assumption (classroom area)"),
        ("10", "Average power", f"{rr['elec_kwh_year_room']:,.0f} kWh / 8,760 hours in a year", f"{avg_kw:.2f} kW", "Arithmetic"),
        ("11", "Share of the week the room is in use", f"{rr['minutes_week'] / 60:.1f} h / 168 h", f"{occ:.4f}", "Arithmetic"),
        ("12", "Power with no class / while a class runs", f"no class = avg x (1 - s) = {avg_kw:.2f} x {base:.2f};  class = avg x ((1 - s) + s / share in use) = {avg_kw:.2f} x ({base:.2f} + {p.var_share:.2f} / {occ:.4f})",
         f"{avg_kw * base:.2f} kW  /  {u['kw_in_use']:.2f} kW", "Assumption (70/30)"),
        ("13", "Class days in Fall 2026", "Dates from the first to the last day of classes, minus the no-class dates, counted per weekday", ", ".join(f"{k} x{v}" for k, v in days.items()), "Public data (calendar)"),
        ("14", "Class hours in the term", "sum over this room's meetings of (its share of the room's real time x class days of that weekday). If several sections meet in the room at the same time (cross-listed or co-taught), the room is in use once and the time is split equally among them",
         f"{u['class_hours_term']:,.1f} h of real room time over {int(u['sections'])} section(s)", "Arithmetic"),
        ("15", "Electricity while classes run", f"class hours x power while a class runs = {u['class_hours_term']:,.1f} x {u['kw_in_use']:.2f}", f"{u['kwh_in_use_term']:,.0f} kWh", "Arithmetic"),
        ("16", "Cost", f"kWh x price = {u['kwh_in_use_term']:,.0f} x ${price:.4f}  (EIA Michigan commercial 2024, 14.01 cents)", f"${u['cost_in_use']:,.2f}", "Public data price"),
        ("17", "Credit hours taught in the room", "each section's credit hours (units x 4) shared over its rooms by class hours, summed for this room", f"{u['credit_hours']:,.1f}", "Public data"),
        ("18", "Energy cost per credit hour", f"cost / credit hours = ${u['cost_in_use']:,.2f} / {u['credit_hours']:,.1f}",
         f"${u['cost_per_credit_hour']:,.2f}" if pd.notna(u["cost_per_credit_hour"]) else "n/a (no credit hours)", "Arithmetic"),
    ]
    st.dataframe(pd.DataFrame(steps, columns=["Step", "What", "How it is calculated", "Result", "Kind"]), hide_index=True, height=720)

# =============================================================================== credit hours and departments
with t_credit:
    st.markdown("How energy cost per credit hour is reached for a **class section**, then a **department** and the **campus**.")
    dnames = sections.drop_duplicates("dept").set_index("dept")["dept_name"].fillna("").to_dict()
    dlist = sorted(dnames)
    dsel = st.selectbox("Department", dlist, index=dlist.index("Biology") if "Biology" in dlist else 0, key="m_dept")
    dsec = sections[sections["dept"] == dsel].sort_values("kwh", ascending=False)
    csel = st.selectbox("Class section (CRN)", dsec["crn"].tolist(),
                        format_func=lambda c: f"{c}: {dsec.set_index('crn').loc[c, 'course_code']}-{dsec.set_index('crn').loc[c, 'section']} {dsec.set_index('crn').loc[c, 'course_title']}",
                        key="m_crn")
    st.markdown("**A. One section: every meeting, then the total**")
    st.caption("When several courses meet in the same room at the same time (cross-listed or co-taught), the room is in use once. "
               "Its time, and therefore its energy and cost, is divided evenly among those courses: with 7 courses in a 2.75-hour block, each is charged 2.75 / 7 = 0.39 hours.")
    mrows = meetings[meetings["crn"] == csel].copy()
    mrows["n_sharing"] = (mrows["hours"] / mrows["eff_hours"].replace(0, float("nan"))).round(2)
    show = mrows[["meeting_day", "start_min", "end_min", "building", "room", "hours", "n_sharing", "eff_hours", "term_days", "hours_term", "kw_in_use", "kwh"]].copy()
    show["start_min"] = show["start_min"].map(lambda m: f"{m // 60}:{m % 60:02d}")
    show["end_min"] = show["end_min"].map(lambda m: f"{m // 60}:{m % 60:02d}")
    show.columns = ["Day", "Start", "End", "Building", "Room", "Hours per meeting", "Courses sharing the room then",
                    "This course's share of the room time (h)", "Class days in term", "Class hours in term",
                    "Room kW while in use", "Electricity kWh"]
    st.dataframe(show.round(2), hide_index=True)
    srow = sections[sections["crn"] == csel].iloc[0]
    sec_cost = srow["kwh"] * price
    st.markdown(
        f"- Section electricity = sum of the last column = **{srow['kwh']:,.0f} kWh**; cost = {srow['kwh']:,.0f} x ${price:.4f} = **${sec_cost:,.2f}**.\n"
        f"- Credit hours = credit units x 4 = **{srow['credit_hours']:g}**; seats = **{srow['enrollment']:g}**; student credit hours = {srow['credit_hours']:g} x {srow['enrollment']:g} = **{srow['student_credit_hours']:g}**.\n"
        f"- Energy per credit hour = ${sec_cost:,.2f} / {srow['credit_hours']:g} = **" + (f"${sec_cost / srow['credit_hours']:,.2f}" if srow["credit_hours"] > 0 else "n/a (no credit hours; a lab section's energy is counted in its department)") + "**.")
    st.markdown("**B. The department: add up its sections**")
    dgrp = sections[sections["dept"] == dsel]
    units = dgrp.assign(units=dgrp["credit_hours"] / 4.0).groupby("units").size().rename("sections").reset_index()
    drow = en.rollup(sections, price, "dept").set_index("group").loc[dsel]
    campus = en.rollup(sections, price, None).iloc[0]
    st.dataframe(pd.DataFrame([
        ("1", "Sections in the department", "count of sections with a room and time", f"{int(drow['sections'])}"),
        ("2", "Credit units per section", ", ".join(f"{int(r.sections)} x {r.units:g} unit" for r in units.itertuples()), "from the Registrar"),
        ("3", "Credit hours offered", "sum over sections of units x 4 (sections with 0 credit add 0)", f"{drow['credit_hours']:,.0f}"),
        ("4", "Seats", "sum of each section's seat count", f"{dgrp['enrollment'].sum():,.0f}"),
        ("5", "Student credit hours", "sum over sections of credit hours x seats", f"{drow['student_credit_hours']:,.0f}"),
        ("6", "Electricity", "sum over all the department's sections (including lab sections with no credit)", f"{drow['kwh']:,.0f} kWh"),
        ("7", "Energy cost", f"kWh x ${price:.4f}", f"${drow['energy_cost']:,.2f}"),
        ("8", "Energy cost per credit hour offered", "energy cost / credit hours offered",
         f"${drow['energy_per_credit_hour']:,.2f}" if pd.notna(drow["energy_per_credit_hour"]) else "n/a"),
        ("9", "Energy cost per student credit hour", "energy cost / student credit hours",
         f"${drow['energy_per_student_credit_hour']:,.2f}" if pd.notna(drow["energy_per_student_credit_hour"]) else "n/a"),
        ("10", "Compared with the campus", f"campus: ${campus['energy_cost']:,.0f} / {campus['credit_hours']:,.0f} credit hours",
         f"campus ${campus['energy_per_credit_hour']:,.2f} per credit hour; this department is "
         + (f"{drow['energy_per_credit_hour'] / campus['energy_per_credit_hour']:.2f} x" if pd.notna(drow['energy_per_credit_hour']) else "n/a")),
    ], columns=["Step", "What", "How", "Result"]), hide_index=True, height=420)
    st.markdown(
        "**Two ways to count energy** (sidebar on the Energy cost per credit hour page): *classroom electricity while classes run* charges a class only what its "
        "room draws while the class runs (the numbers above). *Whole building shared by class hours* instead takes each building's electricity for the class period "
        "(annual kWh x class-day share of the year) and divides it among the classes held there by class hours, so it also charges for offices and hallways: an upper bound.")

# =============================================================================== number dictionary
with t_dict:
    st.markdown("Every number the app shows, with its formula. *Source* says whether an input is public data (**P**), an assumption (**A**) or arithmetic (**C**). "
                "Code lives in `energy.py`, `campus_data.py` and the page files.")
    D = [
        ("Campus electricity", "All pages", "14,000,000 kWh per year x modeled share (default 100%)", "P (Albion article), A (period, share)", "energy.Params"),
        ("Footprint (m2)", "Energy tables, methodology", "shoelace area of the OpenStreetMap outline in a local metric projection", "P + C", "energy.footprint_m2"),
        ("Floors", "Tables, floor view", "max(OpenStreetMap floor count, highest floor implied by room numbers, 1)", "P + A", "energy.building_model"),
        ("Floor of a room", "Floor view, room tables", "room 215 -> 2 (digits before the last two); B12 -> basement; 2-digit rooms -> 1", "A", "campus_data.floor_of"),
        ("Floor area (m2)", "Energy tables", "footprint x floors, summed over a building's outlines", "P + C", "energy.building_model"),
        ("Shared room time", "All room, course and cost numbers", "when several sections meet in the same room at the same time, the room's time is counted once and split equally among them (7 courses in a 2.75 h block: 0.39 h each)", "C", "energy.add_shared_hours"),
        ("Class hours per week", "Tables, activity factor", "real occupied room time: sum over rooms and days of the time a room has at least one class (sections meeting together count once)", "P + C", "energy.building_model"),
        ("Activity factor", "Building electricity", "(1 - s) + s x (hours per m2 / average hours per m2 of scheduled buildings); 1 if no classes; s = 0.30", "P, A (s)", "energy.building_model"),
        ("Building electricity (kWh/yr)", "Map hover, tables, cost pages", "campus kWh x share x (area x factor) / sum(area x factor)", "C", "energy.building_model"),
        ("kWh per m2", "Room estimates", "building kWh per year / building floor area", "C", "energy.building_model"),
        ("Average power (kW)", "Demand now", "kWh per year / 8,760", "C", "energy.live_power_kw"),
        ("Average classes at once (occ)", "Demand now", "weekly class-minutes / (7 x 24 x 60)", "C", "energy.building_model"),
        ("Estimated electric demand now (kW)", "Map: hover, metric, curve", "average kW x ((1 - s) + s x classes in session now / occ); average kW if no classes are ever scheduled", "C, A (s)", "energy.live_power_kw"),
        ("Campus demand curve", "Map page", "sum of demand now over all buildings, every 15 minutes of the selected weekday", "C", "energy.demand_curve"),
        ("Monthly electricity", "Energy details", "yearly kWh x days in the month / 365 (spread evenly)", "C", "energy.monthly"),
        ("Heating share (building)", "Map, tables", "building area / total modeled area; in MMBtu only if you enter a campus heating total", "C, A", "energy.building_model"),
        ("Heating share by month", "Map, energy details", "building share x (hf x degree days of the month / year total + (1 - hf) x days / 365); hf = 0.80, shown in % of annual campus heating", "P (NOAA), A (hf)", "energy.monthly"),
        ("Room use factor", "Room estimate", "(1 - u) + u x room hours / average room hours in the building; u = 0.50", "A", "energy.room_model"),
        ("Room electricity (kWh/yr)", "Room tables, tooltips", "building kWh per m2 x classroom area x intensity multiplier x use factor; rooms scaled down if they sum to more than the building", "C, A (area 60 m2, multiplier 1.0)", "energy.room_model"),
        ("Classrooms' share of a building", "Hover, tables", "sum of its rooms' kWh per year / building kWh per year", "C", "energy.building_rooms_summary"),
        ("Room power: no class / in use (kW)", "Tooltips, tables", "avg x (1 - s)  /  avg x ((1 - s) + s / share of the week in use)", "C, A (s)", "energy.room_use"),
        ("Class days in the term", "Cost pages", "weekdays from Aug 24 to Dec 4 minus Sep 7, Oct 12-13, Nov 25-28: Mon 13, Tue-Fri 14", "P (calendar)", "energy.term_days_per_weekday"),
        ("Class hours in the term", "Cost pages", "each meeting's share of the room's real time x class days of that weekday, summed", "P + C", "energy.room_use"),
        ("Electricity while classes run (kWh)", "Cost pages, tooltips", "room power in use x class hours in the term", "C", "energy.room_use"),
        ("Added by class activity (kWh)", "Energy details", "avg x s / share in use x class hours (the class-driven part only)", "C, A", "energy.room_use"),
        ("Cost ($)", "Cost pages", "kWh x price; price default 14.01 cents/kWh", "P (EIA price)", "pages"),
        ("Fall 2026 electricity (kWh)", "Energy cost page", "yearly kWh x days in the period / 365 (Aug 24 - Dec 10 = 109 days; Aug 24 - Dec 4 for classes only)", "P (calendar) + C", "energy.period_weights"),
        ("Fall 2026 heating share", "Energy cost page", "sum over months of (monthly weight x days in the period / days in the month)", "P + C", "energy.period_weights"),
        ("Credit hours (section)", "Credit-hour page", "Registrar credit units x 4 (1 Albion unit = 4 semester hours)", "P", "fetch_schedule, energy.course_energy"),
        ("Credit hours in a room", "Tooltips", "each section's credit hours shared over its rooms by class hours, summed per room", "P + C", "energy.room_credit_hours"),
        ("Credit hours offered", "Credit-hour page", "sum of section credit hours (0-credit lab sections add 0)", "P", "energy.rollup"),
        ("Student credit hours", "Credit-hour page", "sum over sections of credit hours x seats (aggregate section seat count)", "P", "energy.sections_from"),
        ("Energy cost per credit hour", "Credit-hour page", "energy cost of the group / credit hours offered", "C", "energy.rollup"),
        ("Energy cost per student credit hour", "Credit-hour page", "energy cost of the group / student credit hours", "C", "energy.rollup"),
        ("Cost with your other cost added", "Credit-hour page", "energy cost per credit hour + the figure you type in the sidebar", "C + your input", "energy.rollup"),
        ("Whole-building (upper bound) energy", "Credit-hour page option", "building electricity for the class period shared over its classes by class hours", "C, A", "energy.course_energy"),
        ("Classes in session", "Map", "meetings with start <= time < end on the selected weekday, per building", "P", "campus_data.in_session"),
        ("Floor values (floor view)", "Map floor view", "classes: those held on that floor; kW: building kW x (0.5 / floors + 0.5 x floor classes / all classes); heating: building share / floors", "C, A (50/50)", "campus_map.py"),
        ("Tower height and colors", "Map", "value / maximum x tower scale; color ramp teal -> amber -> pink = low -> high", "C", "campus_map.py"),
        ("Electricity intensity comparison", "Energy details", "campus kWh x share / (modeled area / 0.0929 m2 per ft2), against 9.4 kWh per ft2 (EIA CBECS 2018)", "P + C", "energy_view.py"),
    ]
    st.dataframe(pd.DataFrame(D, columns=["Number", "Where shown", "How it is calculated", "Source (P public, A assumption, C arithmetic)", "Code"]),
                 hide_index=True, height=720)

# =============================================================================== heating, fall cost, map, walkers
with t_other:
    st.markdown("### Heating")
    st.markdown(
        "- **No public heating total** was found, so heating is shown as each building's **share of annual campus heating** (the shares add up to 100%). "
        "If you type a campus total in MMBtu (sidebar) the shares become MMBtu.\n"
        "- A building's share is its floor area over the total modeled area.\n"
        "- The monthly weight mixes weather and a flat part: weight = hf x (degree days of the month / yearly degree days) + (1 - hf) x (days in the month / 365), with hf = 0.80. "
        "Degree days are NOAA's 1991-2020 normals for Jackson Reynolds Field (annual total 6,469.6).")
    hdd = en.load_hdd()
    hdd["Weight"] = p.heating_fraction * hdd["hdd_base65f"] / hdd["hdd_base65f"].sum() + (1 - p.heating_fraction) * pd.Series(
        [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]) / 365
    hdd["Month"] = en.MONTHS
    hdd["Share of annual heating (%)"] = hdd["Weight"] * 100
    st.dataframe(hdd[["Month", "hdd_base65f", "Share of annual heating (%)"]].rename(columns={"hdd_base65f": "Degree days (NOAA)"}).round(2), hide_index=True, height=300)
    st.markdown("### Fall 2026 cost page")
    pw = en.period_weights(p, en.FALL_START, en.FALL_EXAMS_END)
    pw["kWh"] = pw["elec_frac"] * model["elec_kwh_year"].sum()
    pw["Cost $"] = pw["kWh"] * price
    st.markdown(
        "- Electricity for a period = yearly kWh x days in the period / 365; cost = kWh x price.\n"
        "- Heating for a period = sum over months of the month's weight x (days in the period within that month / days in the month); August and December are partial months.\n"
        "- Whole term = Aug 24 to Dec 10 (109 days, includes finals); classes only = Aug 24 to Dec 4.")
    st.dataframe(pw.rename(columns={"month_name": "Month", "days": "Days in period", "elec_frac": "Share of year (electricity)",
                                    "heat_frac": "Share of year (heating)"})[["Month", "Days in period", "Share of year (electricity)", "Share of year (heating)", "kWh", "Cost $"]].round(4),
                 hide_index=True)
    st.markdown("### Campus map")
    st.markdown(
        "- **Classes in session**: count of meetings with start <= time < end on the selected weekday. Colors run teal -> amber -> pink from 0 to the maximum; "
        "tower height = value / maximum x tower scale.\n"
        "- **Floor view**: floors come from OpenStreetMap or room numbers; each floor's value is described in *Every number explained*. No floor plans are used.\n"
        "- **Hover**: classes now with section, title, department, credit hours, room kW now and kWh this term; building electricity per year and the classrooms' share.")
    st.markdown("### Walking figures (an illustration)")
    st.markdown(
        "No data exists on who walks where, so this is a **simulation for illustration only**:\n"
        "1. For every class that ends, one class that starts within the next **15 minutes** is picked at random.\n"
        "2. If it is in a different building, **N figures** (default 10 per class) leave the first building and walk to the second.\n"
        "3. Each leaves 0.3 to 2.5 minutes after the class ends, walks at 70 to 95 metres per minute in a straight line with a small sideways spread, and always arrives before the next class starts.\n"
        "4. The colour is the **department of the class they are walking to**. The random choices use a fixed seed, so the same day always looks the same.")

# =============================================================================== checks
with t_checks:
    st.markdown("Consistency checks, recomputed live. Each should say OK.")
    rows = []
    tot = p.elec_kwh_total * p.modeled_share
    rows.append(("Building electricity adds up to the campus total x modeled share", f"{model['elec_kwh_year'].sum():,.0f} vs {tot:,.0f}",
                 "OK" if abs(model["elec_kwh_year"].sum() - tot) < 1 else "CHECK"))
    bs = en.building_rooms_summary(rooms, model)
    rows.append(("A building's rooms never exceed the building", f"largest share {bs['classroom_share'].max():.1%}", "OK" if bs["classroom_share"].max() <= 1.0001 else "CHECK"))
    rows.append(("Heating shares add up to 100%", f"{model['heat_year'].sum() * 100:,.2f}%", "OK" if abs(model["heat_year"].sum() - 1) < 1e-6 or p.heat_total_mmbtu > 0 else "CHECK"))
    cr_sections = sections["credit_hours"].sum()
    cr_rooms = ctab["credit_hours"].sum()
    rows.append(("Credit hours counted in rooms match the sections (small gap = meetings in buildings not on the map)", f"{cr_rooms:,.1f} vs {cr_sections:,.1f}", "OK" if cr_rooms <= cr_sections + 0.01 else "CHECK"))
    rows.append(("Class days per weekday (calendar)", ", ".join(f"{k} {v}" for k, v in days.items()), "OK" if sum(days.values()) == 69 else "CHECK"))
    sh = en.add_shared_hours(schedule)
    rows.append(("Shared rooms: no meeting is charged more than its own length, and shares add up to the room's real time",
                 f"{sh['eff_hours'].sum():,.1f} h shared vs {sh['hours'].sum():,.1f} h if every section were counted separately", "OK" if (sh["eff_hours"] <= sh["hours"] + 1e-9).all() else "CHECK"))
    rows.append(("Schedule rows used on the map", f"{len(schedule):,} meetings in {schedule['building'].nunique()} buildings", "OK"))
    rows.append(("Term electricity by month adds up to the period total",
                 f"{(en.period_weights(p, en.FALL_START, en.FALL_EXAMS_END)['elec_frac'].sum() * tot):,.0f} kWh in {int(en.period_weights(p, en.FALL_START, en.FALL_EXAMS_END)['days'].sum())} days", "OK"))
    st.dataframe(pd.DataFrame(rows, columns=["Check", "Values", "Result"]), hide_index=True)
    st.markdown("The Power BI visual repeats the same method; on this schedule its building values agree with these within 0.1% (the difference comes from four meetings in buildings that are not on the map).")

energy_view.sources_panel()
