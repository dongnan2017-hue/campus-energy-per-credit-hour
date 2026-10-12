"""Modeled (NOT metered) electricity and heating estimates for each campus building and room.

Albion publishes (as far as we could verify) only one campus-wide electricity number, from a college news article,
and no public heating total. Everything per building/room is therefore an allocation, shown as an estimate.
Sources are listed in SOURCES.md and in the app's "Sources" panel.
"""
from __future__ import annotations

import calendar
import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MMBTU_TO_KWH = 293.07107          # 1 MMBtu = 293.07107 kWh (standard unit conversion)
FT2_TO_M2 = 0.09290304
HDD_PATH = Path(__file__).parent / "data" / "hdd_jackson_1991_2020.csv"
MONTHS = [calendar.month_abbr[m] for m in range(1, 13)]

# Albion College news article, "Albion College Joins Climate Leadership Network, Commits to Action"
# (posted Dec 18, 2020): "Currently, he says, the College uses about 14 million kilowatt hours."
# The article does not state the period (assumed to be one year).
ALBION_ELEC_KWH = 14_000_000.0

# OpenStreetMap buildings that are not Albion College facilities
NOT_COLLEGE = {"First United Methodist Church", "Stahl Family Dentistry"}


@dataclass
class Params:
    elec_kwh_total: float = ALBION_ELEC_KWH   # campus electricity per year
    modeled_share: float = 1.0                # share of that electricity used by the buildings we model
    heat_total_mmbtu: float = 0.0             # campus heating fuel per year; 0 = unknown -> shown as shares
    heating_fraction: float = 0.80            # share of heating fuel that is weather-driven space heating
    var_share: float = 0.30                   # share of building electricity that follows class activity
    classroom_area_m2: float = 60.0           # typical classroom floor area (ASSUMPTION, adjustable)
    room_use_share: float = 0.50              # within classrooms: share split by scheduled hours (rest equal)
    room_overrides: tuple = ()                # ((building, classroom_area_m2, intensity_multiplier), ...) per building
    unnamed_floors: int = 1

    @property
    def heat_is_relative(self) -> bool:
        return self.heat_total_mmbtu <= 0


def load_hdd() -> pd.DataFrame:
    return pd.read_csv(HDD_PATH)


def footprint_m2(ring) -> float:
    """Polygon area in m2 from a lon/lat ring (local equirectangular projection, measured from the first vertex for precision)."""
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    kx, ky = 111320.0 * math.cos(lat0), 110574.0
    x0, y0 = ring[0][0], ring[0][1]
    xs = [(p[0] - x0) * kx for p in ring]
    ys = [(p[1] - y0) * ky for p in ring]
    a = 0.0
    for i in range(len(ring) - 1):
        a += xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
    return abs(a) / 2.0


LAB_UNITS = 0.25  # units a lab takes from its lecture course


def move_lab_credit(schedule: pd.DataFrame) -> pd.DataFrame:
    """Gives each lab section LAB_UNITS (0.25 unit = 1 credit hour) taken from the sections of its lecture course.

    A lab is a zero-credit course whose code is the lecture code plus 'L' (BIOL 195L belongs to BIOL 195). The
    lecture course keeps its other units. Students take one lab section, so a student's credit hours stay the same;
    labs just carry their share. Zero-credit courses that are not labs (a colloquium) stay at zero.
    """
    s = schedule.copy()
    for c in ("credit_hours", "credit_units"):
        s[c] = pd.to_numeric(s[c], errors="coerce") if c in s.columns else np.nan
    if s["credit_hours"].isna().all() and s["credit_units"].notna().any():
        s["credit_hours"] = s["credit_units"] * CREDIT_HOURS_PER_UNIT
    code = s["course_code"].astype(str)
    parent = code.str.replace(r"L$", "", regex=True)
    lecture_hours = s.groupby("course_code")["credit_hours"].max()
    is_lab = code.str.endswith("L") & (s["credit_hours"].fillna(0) == 0) & parent.map(lecture_hours).fillna(0).gt(0)
    take = LAB_UNITS * CREDIT_HOURS_PER_UNIT
    lecture_codes = set(parent[is_lab])
    is_lecture = code.isin(lecture_codes) & (s["credit_hours"] >= take)
    s.loc[is_lab, "credit_hours"] = take
    s.loc[is_lecture, "credit_hours"] = s.loc[is_lecture, "credit_hours"] - take
    s["credit_units"] = s["credit_hours"] / CREDIT_HOURS_PER_UNIT
    return s


def add_shared_hours(schedule: pd.DataFrame) -> pd.DataFrame:
    """Adds `hours` (meeting length) and `eff_hours` (that meeting's SHARE of the room's real time).

    When several sections meet in the same room at the same time (cross-listed or co-taught courses) the room is
    in use once, not once per section. The room's time is therefore split equally among the meetings covering it,
    so a room's effective hours are never more than the real time it is occupied.
    """
    s = schedule.copy()
    s["hours"] = (s["end_min"] - s["start_min"]) / 60.0
    s["eff_hours"] = s["hours"]
    named = s["room"].astype(str).str.strip().ne("") & s["room"].astype(str).ne("(room not listed)")
    for _key, g in s[named].groupby(["building", "room", "meeting_day"]):
        if len(g) < 2:
            continue
        pts = sorted(set(g["start_min"]) | set(g["end_min"]))
        eff = pd.Series(0.0, index=g.index)
        for a, c in zip(pts[:-1], pts[1:]):
            cover = g.index[(g["start_min"] <= a) & (g["end_min"] >= c)]
            if len(cover):
                eff.loc[cover] += (c - a) / 60.0 / len(cover)
        s.loc[g.index, "eff_hours"] = eff
    return s


def building_model(buildings: pd.DataFrame, schedule: pd.DataFrame, p: Params) -> pd.DataFrame:
    """One row per named college building with estimated area, electricity and heating per year.

    Heating is returned in MMBtu when a campus total is supplied, otherwise as a fraction of the annual
    campus total (so all buildings together add up to 1.0).
    """
    b = buildings[(buildings["name"] != "") & ~buildings["name"].isin(NOT_COLLEGE)].copy()
    b["footprint_m2"] = b["polygon"].map(lambda poly: footprint_m2(poly[0]))

    sched_floor = schedule.groupby("building")["floor"].max()

    def floors(row) -> int:
        try:
            lv = int(float(row["levels"]))
        except (TypeError, ValueError):
            lv = 0
        return max(lv, int(sched_floor.get(row["name"], 0)), p.unnamed_floors)

    b["floors"] = b.apply(floors, axis=1)
    b["area_m2"] = b["footprint_m2"] * b["floors"]
    m = (b.groupby("name").agg(area_m2=("area_m2", "sum"), footprint_m2=("footprint_m2", "sum"),
                               floors=("floors", "max"), lon=("lon", "mean"), lat=("lat", "mean"))
         .reset_index())

    shared = add_shared_hours(schedule)
    mins = shared.assign(minutes=shared["eff_hours"] * 60.0).groupby("building").agg(
        minutes_week=("minutes", "sum"), rooms=("room", "nunique"))
    m = m.merge(mins, how="left", left_on="name", right_index=True)
    m["minutes_week"] = m["minutes_week"].fillna(0.0)
    m["rooms"] = m["rooms"].fillna(0).astype(int)
    m["class_hours_week"] = m["minutes_week"] / 60.0
    m["occ_mean"] = m["minutes_week"] / (7 * 24 * 60.0)       # average number of classes running at once

    base_share = 1.0 - p.var_share
    sched = m["class_hours_week"] > 0
    d_avg = m.loc[sched, "class_hours_week"].sum() / max(m.loc[sched, "area_m2"].sum(), 1.0)
    density = m["class_hours_week"] / m["area_m2"].clip(lower=1.0)
    m["elec_factor"] = np.where(sched, base_share + p.var_share * density / max(d_avg, 1e-9), 1.0)

    raw = m["area_m2"] * m["elec_factor"]
    m["elec_kwh_year"] = p.elec_kwh_total * p.modeled_share * raw / raw.sum()   # allocation adds up to the total
    m["elec_kwh_m2"] = m["elec_kwh_year"] / m["area_m2"].clip(lower=1.0)

    heat_total = p.heat_total_mmbtu if p.heat_total_mmbtu > 0 else 1.0
    m["heat_year"] = heat_total * m["area_m2"] / m["area_m2"].sum()
    return m


def monthly(model: pd.DataFrame, p: Params, hdd: pd.DataFrame | None = None, year: int = 2026) -> pd.DataFrame:
    """Building x month: electricity (kWh) and heating (MMBtu, or fraction of annual campus heating)."""
    hdd = hdd if hdd is not None else load_hdd()
    h = hdd.set_index("month")["hdd_base65f"]
    days = pd.Series({m: calendar.monthrange(year, m)[1] for m in range(1, 13)})
    heat_w = p.heating_fraction * h / h.sum() + (1 - p.heating_fraction) * days / days.sum()
    elec_w = days / days.sum()
    rows = []
    for _, r in model.iterrows():
        for mth in range(1, 13):
            rows.append({"name": r["name"], "month": mth, "month_name": MONTHS[mth - 1],
                         "elec_kwh": r["elec_kwh_year"] * elec_w[mth],
                         "heat": r["heat_year"] * heat_w[mth]})
    return pd.DataFrame(rows)


def room_model(schedule: pd.DataFrame, model: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Share of each building's electricity attributed to its scheduled classrooms (relative, modeled)."""
    s = add_shared_hours(schedule)
    s["minutes"] = s["eff_hours"] * 60.0
    s["room"] = s["room"].replace("", "(room not listed)")
    r = s.groupby(["building", "room"]).agg(minutes_week=("minutes", "sum"), meetings=("minutes", "size")).reset_index()
    r = r.merge(model[["name", "elec_kwh_m2"]], how="inner", left_on="building", right_on="name")
    mean_min = r.groupby("building")["minutes_week"].transform("mean")
    use_factor = (1 - p.room_use_share) + p.room_use_share * r["minutes_week"] / mean_min.clip(lower=1e-9)
    # building electricity per m2 x that building's classroom area x its intensity multiplier,
    # weighted up or down by how much the room is used
    area_map = {b: a for b, a, _m in p.room_overrides}
    mult_map = {b: m for b, _a, m in p.room_overrides}
    area = r["building"].map(area_map).fillna(p.classroom_area_m2)
    mult = r["building"].map(mult_map).fillna(1.0)
    r["elec_kwh_year_room"] = r["elec_kwh_m2"] * area * mult * use_factor
    # the rooms of a building can never use more than the building itself
    cap = r["building"].map(model.set_index("name")["elec_kwh_year"])
    total = r.groupby("building")["elec_kwh_year_room"].transform("sum").clip(lower=1e-9)
    r["elec_kwh_year_room"] = r["elec_kwh_year_room"] * (cap / total).clip(upper=1.0)
    r["class_hours_week"] = r["minutes_week"] / 60.0
    return r.drop(columns=["name", "elec_kwh_m2"]).sort_values(["building", "elec_kwh_year_room"], ascending=[True, False])


def live_power_kw(model: pd.DataFrame, counts: dict, p: Params) -> pd.Series:
    """Estimated electric demand (kW) per building at a moment, given the number of ROOMS in use per building."""
    base_share = 1.0 - p.var_share
    avg_kw = model["elec_kwh_year"] / 8760.0
    occ = model["name"].map(counts).fillna(0.0)
    ratio = np.where(model["occ_mean"] > 0, occ / model["occ_mean"].clip(lower=1e-9), 1.0)
    factor = np.where(model["occ_mean"] > 0, base_share + p.var_share * ratio, 1.0)
    return pd.Series(avg_kw.to_numpy() * factor, index=model["name"])


def demand_curve(schedule: pd.DataFrame, model: pd.DataFrame, day: str, p: Params,
                 step: int = 15, start: int = 7 * 60, end: int = 22 * 60) -> pd.DataFrame:
    """Modeled campus electric demand (kW) through one weekday."""
    d = schedule[schedule["meeting_day"] == day]
    rows = []
    for t in range(start, end + 1, step):
        now = d[(d["start_min"] <= t) & (t < d["end_min"])]
        counts = now.groupby("building")["room"].nunique().to_dict()
        rows.append((t, float(live_power_kw(model, counts, p).sum())))
    return pd.DataFrame(rows, columns=["minute", "kw"])


def room_live(schedule: pd.DataFrame, rooms: pd.DataFrame, building: str, day: str, minute: int, p: Params) -> pd.DataFrame:
    """Per-classroom modeled electricity for one building: demand now (kW), energy today (kWh), energy per year (kWh).

    A room's yearly estimate (room_model) is spread over time like the building: a constant part plus a part
    that is only on while a class is in session. Relative, modeled values only; nothing here is metered.
    """
    r = rooms[rooms["building"] == building].copy()
    if r.empty:
        return r
    s = schedule[(schedule["building"] == building)].copy()
    s["room"] = s["room"].replace("", "(room not listed)")
    today = s[s["meeting_day"] == day]
    hours_today = (today.assign(h=(today["end_min"] - today["start_min"]) / 60.0).groupby("room")["h"].sum())
    now = today[(today["start_min"] <= minute) & (minute < today["end_min"])]["room"].unique()
    base_share = 1.0 - p.var_share
    avg_kw = r["elec_kwh_year_room"] / 8760.0
    occ_mean = (r["minutes_week"] / (7 * 24 * 60.0)).clip(lower=1e-9)       # average share of time in session
    in_now = r["room"].isin(now)
    r["in_session_now"] = in_now
    r["kw_now"] = avg_kw * (base_share + p.var_share * in_now.astype(float) / occ_mean)
    h_today = r["room"].map(hours_today).fillna(0.0)
    r["kwh_today"] = avg_kw * base_share * 24.0 + avg_kw * p.var_share / occ_mean * h_today
    r["class_hours_today"] = h_today
    return r.sort_values("kw_now", ascending=False)


# Fall 2026 instructional calendar, Albion College Registrar "Academic Calendar"
# https://www.albion.edu/offices/registrar/academic-calendar/ (first day Aug 24, last day Dec 4;
# no classes Sep 7, Oct 12-13, Nov 25-28; final exams Dec 7-10 are not counted because exam times differ).
TERM_START = dt.date(2026, 8, 24)
TERM_END = dt.date(2026, 12, 4)
NO_CLASS = ([dt.date(2026, 9, 7), dt.date(2026, 10, 12), dt.date(2026, 10, 13)]
            + [dt.date(2026, 11, d) for d in range(25, 29)])
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def term_days_per_weekday() -> dict:
    """How many times each weekday occurs in the Fall 2026 instructional period (holidays removed)."""
    counts = {d: 0 for d in DAY_NAMES}
    day = TERM_START
    while day <= TERM_END:
        if day.weekday() < 5 and day not in NO_CLASS:
            counts[DAY_NAMES[day.weekday()]] += 1
        day += dt.timedelta(days=1)
    return counts


def room_use(schedule: pd.DataFrame, rooms: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Modeled electricity used by each classroom while classes are in session, per term.

    kw_in_use  = the room's average demand x (constant part + class-driven part / share of time in use)
    kwh_in_use = kw_in_use x class hours in the term   (everything the room draws while a class runs)
    kwh_extra  = only the class-driven part of that energy (what the class adds on top of the constant load)
    Relative, modeled values: nothing here is metered.
    """
    days = term_days_per_weekday()
    s = add_shared_hours(schedule)
    s["room"] = s["room"].replace("", "(room not listed)")
    s["term_days"] = s["meeting_day"].map(days).fillna(0)
    s["hours_term"] = s["eff_hours"] * s["term_days"]          # shared when sections meet together
    per = s.groupby(["building", "room"]).agg(
        sessions_term=("term_days", "sum"), class_hours_term=("hours_term", "sum"),
        class_hours_week=("eff_hours", "sum")).reset_index()
    r = rooms[["building", "room", "elec_kwh_year_room", "minutes_week"]].merge(per, on=["building", "room"], how="left")
    base_share = 1.0 - p.var_share
    avg_kw = r["elec_kwh_year_room"] / 8760.0
    occ_mean = (r["minutes_week"] / (7 * 24 * 60.0)).clip(lower=1e-9)
    r["kw_in_use"] = avg_kw * (base_share + p.var_share / occ_mean)
    r["kwh_in_use_term"] = r["kw_in_use"] * r["class_hours_term"]
    r["kwh_extra_term"] = avg_kw * p.var_share / occ_mean * r["class_hours_term"]
    r["kwh_per_class_hour"] = r["kw_in_use"]
    return r.drop(columns=["minutes_week"]).sort_values("kwh_in_use_term", ascending=False)


# Fall 2026 term for cost estimates (Registrar academic calendar): classes Aug 24 - Dec 4, final exams Dec 7 - 10.
FALL_START = dt.date(2026, 8, 24)
FALL_CLASSES_END = dt.date(2026, 12, 4)
FALL_EXAMS_END = dt.date(2026, 12, 10)


def period_weights(p: Params, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Share of the ANNUAL electricity and heating that falls in [start, end], month by month.

    Electricity is spread evenly over days; heating follows heating degree days (plus a flat part).
    """
    hdd = load_hdd().set_index("month")["hdd_base65f"]
    year = start.year
    days_in = {m: calendar.monthrange(year, m)[1] for m in range(1, 13)}
    total_days = sum(days_in.values())
    heat_w = p.heating_fraction * hdd / hdd.sum() + (1 - p.heating_fraction) * pd.Series(days_in) / total_days
    rows = []
    for m in range(1, 13):
        first, last = dt.date(year, m, 1), dt.date(year, m, days_in[m])
        lo, hi = max(first, start), min(last, end)
        d = (hi - lo).days + 1 if hi >= lo else 0
        if d <= 0:
            continue
        rows.append({"month": m, "month_name": MONTHS[m - 1], "days": d,
                     "elec_frac": d / total_days, "heat_frac": float(heat_w[m]) * d / days_in[m]})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- energy per credit hour
CREDIT_HOURS_PER_UNIT = 4.0   # Albion Registrar FAQ: "one unit of credit is equal to four semester hours of credit."


def course_energy(schedule: pd.DataFrame, rooms: pd.DataFrame, model: pd.DataFrame, p: Params,
                  mode: str = "in_use") -> pd.DataFrame:
    """Electricity (kWh, Fall 2026 class days) attributed to every class meeting row.

    mode "in_use":   the room's electricity while that class runs (room_use demand x hours x class days).
    mode "building": the building's whole-term electricity shared across the classes held in it, by class hours
                     (an upper bound: it also charges classes for offices, hallways and other non-class use).
    """
    days = term_days_per_weekday()
    s = add_shared_hours(move_lab_credit(schedule))
    s["room"] = s["room"].replace("", "(room not listed)")
    s["term_days"] = s["meeting_day"].map(days).fillna(0)
    s["hours_term_raw"] = s["hours"] * s["term_days"]            # the meeting's own length in the term
    s["hours_term"] = s["eff_hours"] * s["term_days"]            # its share of the room's real time (energy is counted once)
    for c in ("credit_hours", "credit_units", "enrollment"):
        s[c] = pd.to_numeric(s[c], errors="coerce") if c in s.columns else np.nan
    if s["credit_hours"].isna().all() and s["credit_units"].notna().any():
        s["credit_hours"] = s["credit_units"] * CREDIT_HOURS_PER_UNIT
    use = room_use(schedule, rooms, p)[["building", "room", "kw_in_use"]]
    s = s.merge(use, on=["building", "room"], how="left")
    if mode == "in_use":
        s["kwh"] = s["kw_in_use"] * s["hours_term"]
    else:
        frac = float(period_weights(p, FALL_START, FALL_CLASSES_END)["elec_frac"].sum())
        building_kwh = model.set_index("name")["elec_kwh_year"] * frac
        tot_hours = s.groupby("building")["hours_term"].transform("sum").clip(lower=1e-9)
        s["kwh"] = s["building"].map(building_kwh) * s["hours_term"] / tot_hours
    s["modeled"] = s["kwh"].notna()
    s["kwh"] = s["kwh"].fillna(0.0)
    if "department" in s.columns:
        s["dept"] = s["department"].where(s["department"].astype(str) != "", s["course_code"].astype(str).str.split().str[0])
    else:
        s["dept"] = s["course_code"].astype(str).str.split().str[0]
    return s


def sections_from(meetings: pd.DataFrame) -> pd.DataFrame:
    """One row per section (CRN): energy, class hours, credit hours and enrollment."""
    g = meetings.groupby("crn")
    sec = g.agg(course_code=("course_code", "first"), dept=("dept", "first"),
                course_title=("course_title", "first"), section=("section", "first"),
                dept_name=("dept", "first"),
                buildings=("building", lambda x: ", ".join(sorted(set(x)))),
                kwh=("kwh", "sum"), class_hours_term=("hours_term", "sum"),
                credit_hours=("credit_hours", "first"), enrollment=("enrollment", "first"),
                unmodeled_rows=("modeled", lambda x: int((~x).sum())), total_rows=("modeled", "size")).reset_index()
    sec["credit_hours"] = sec["credit_hours"].fillna(0.0)
    # Only credit hours taught in modeled classrooms count: a section whose every meeting is outside the modeled
    # classrooms (fitness centers, rooms not listed) has no classroom energy, so it must not dilute the average.
    sec["credit_hours_outside_classrooms"] = sec["credit_hours"].where(sec["unmodeled_rows"] >= sec["total_rows"], 0.0)
    sec["credit_hours"] = sec["credit_hours"] - sec["credit_hours_outside_classrooms"]
    sec["enrollment"] = sec["enrollment"].fillna(0.0)
    sec["student_credit_hours"] = sec["credit_hours"] * sec["enrollment"]
    return sec


def rollup(sections: pd.DataFrame, price: float, by: str | None, other_per_credit_hour: float = 0.0) -> pd.DataFrame:
    """Energy cost per credit hour, by department or course (by=None gives one campus row).

    Sections with no credit (labs) keep their energy in the course total but add no credit hours, so the
    cost of lab rooms is carried by the course they belong to.
    """
    sec = sections.assign(_all="Campus") if by is None else sections
    key = "_all" if by is None else by
    g = sec.groupby(key)
    out = g.agg(sections=("crn", "count"), class_hours_term=("class_hours_term", "sum"), kwh=("kwh", "sum"),
                credit_hours=("credit_hours", "sum"), student_credit_hours=("student_credit_hours", "sum")).reset_index()
    out = out.rename(columns={key: "group"})
    out["energy_cost"] = out["kwh"] * price
    out["energy_per_credit_hour"] = out["energy_cost"] / out["credit_hours"].replace(0, np.nan)
    out["energy_per_student_credit_hour"] = out["energy_cost"] / out["student_credit_hours"].replace(0, np.nan)
    out["total_per_credit_hour"] = out["energy_per_credit_hour"] + other_per_credit_hour
    return out


def building_rooms_summary(rooms: pd.DataFrame, model: pd.DataFrame) -> pd.DataFrame:
    """Per building: how many classrooms the schedule uses and their combined modeled electricity."""
    g = rooms.groupby("building").agg(classrooms=("room", "count"), class_hours_week=("class_hours_week", "sum"),
                                      classroom_kwh_year=("elec_kwh_year_room", "sum"))
    g = g.join(model.set_index("name")["elec_kwh_year"].rename("building_kwh_year"), how="left")
    g["classroom_share"] = g["classroom_kwh_year"] / g["building_kwh_year"].clip(lower=1e-9)
    return g.reset_index()


# ----------------------------------------------------------------------------- classroom credit hours (for tooltips)
def room_credit_hours(meetings: pd.DataFrame) -> pd.DataFrame:
    """Credit hours taught in each room: a section's credit hours are split over its rooms by class hours."""
    sec_hours = meetings.groupby("crn")["hours_term"].transform("sum").clip(lower=1e-9)
    m = meetings.assign(_share=meetings["credit_hours"].fillna(0.0) * meetings["hours_term"] / sec_hours)
    return m.groupby(["building", "room"]).agg(credit_hours=("_share", "sum"), sections=("crn", "nunique")).reset_index()


def classroom_table(schedule: pd.DataFrame, rooms: pd.DataFrame, model: pd.DataFrame, p: Params,
                    price: float | None = None) -> pd.DataFrame:
    """One row per classroom: credit hours taught, class hours, demand while in use, electricity this term (and cost)."""
    meetings = course_energy(schedule, rooms, model, p, "in_use")
    t = room_use(schedule, rooms, p).merge(room_credit_hours(meetings), on=["building", "room"], how="left")
    t["credit_hours"] = t["credit_hours"].fillna(0.0)
    t["sections"] = t["sections"].fillna(0).astype(int)
    t["cost_in_use"] = t["kwh_in_use_term"] * price if price is not None else np.nan
    t["cost_per_credit_hour"] = t["cost_in_use"] / t["credit_hours"].replace(0, np.nan)
    return t


def rooms_text(table: pd.DataFrame, key: str, n: int = 6, price: float | None = None) -> dict:
    """Tooltip text per group: 'room: credit hours, kWh this term (cost) | ...' for the busiest rooms."""
    out = {}
    for k, g in table.sort_values("kwh_in_use_term", ascending=False).groupby(key):
        parts = []
        for r in g.head(n).itertuples():
            txt = f"{r.room}: {r.credit_hours:.1f} credit hrs, {r.kwh_in_use_term:,.0f} kWh"
            if price:
                txt += f" (${r.kwh_in_use_term * price:,.0f})"
            parts.append(txt)
        extra = len(g) - n
        out[k] = " | ".join(parts) + (f" | +{extra} more" if extra > 0 else "")
    return out


def dept_rooms_text(meetings: pd.DataFrame, price: float, n: int = 5) -> dict:
    """Tooltip text per department: the rooms its sections use, with credit hours and electricity."""
    sec_hours = meetings.groupby("crn")["hours_term"].transform("sum").clip(lower=1e-9)
    m = meetings.assign(_cr=meetings["credit_hours"].fillna(0.0) * meetings["hours_term"] / sec_hours)
    g = m.groupby(["dept", "building", "room"]).agg(cr=("_cr", "sum"), kwh=("kwh", "sum")).reset_index()
    out = {}
    for d, grp in g.sort_values("kwh", ascending=False).groupby("dept"):
        parts = [f"{r.building} {r.room}: {r.cr:.1f} credit hrs, {r.kwh:,.0f} kWh (${r.kwh * price:,.0f})" for r in grp.head(n).itertuples()]
        extra = len(grp) - n
        out[d] = " | ".join(parts) + (f" | +{extra} more" if extra > 0 else "")
    return out
