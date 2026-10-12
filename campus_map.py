"""Albion College campus activity simulator (Streamlit).

Shows how many classes are in session in every building as the day plays,
using only public class start/end times. Run:  streamlit run app.py
"""
from __future__ import annotations

import base64
import struct
import zlib
from datetime import timedelta

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import campus_data as cd
import energy as en
import energy_view


STEP = 5        # minutes per step on the activity chart
CLOCK_STEP = 1  # minutes per step on the time slider (walkers need fine steps)

GROUP_COLORS = [
    [77, 201, 246], [246, 112, 25], [245, 55, 148], [172, 194, 54], [133, 73, 186], [0, 169, 80],
    [255, 212, 59], [255, 107, 107], [83, 123, 196], [232, 195, 185], [22, 160, 133], [189, 195, 199],
]


@st.cache_resource
def person_icon_url() -> str:
    """A small white person silhouette (head, body, legs) as a PNG data URL; deck.gl tints it per group."""
    w, h = 48, 64
    px = [[0] * w for _ in range(h)]

    def fill(test):
        for y in range(h):
            for x in range(w):
                if test(x + 0.5, y + 0.5):
                    px[y][x] = 255

    fill(lambda x, y: (x - 24) ** 2 + (y - 11) ** 2 <= 9.5 ** 2)                                  # head
    fill(lambda x, y: 14 <= x <= 34 and 23 <= y <= 43 and ((x - 24) / 10.5) ** 4 + ((y - 33) / 10.5) ** 4 <= 1.35)  # torso
    fill(lambda x, y: (8 <= x <= 15 and 25 <= y <= 42) or (33 <= x <= 40 and 25 <= y <= 42))       # arms
    fill(lambda x, y: (16 <= x <= 23 and 43 <= y <= 62) or (25 <= x <= 32 and 43 <= y <= 62))      # legs
    raw = b"".join(b"\x00" + b"".join(bytes((255, 255, 255, a)) for a in row) for row in px)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


@st.cache_data
def get_trips(_schedule: pd.DataFrame, key: str, day: str, per_class: int, pos: tuple) -> pd.DataFrame:
    return cd.build_trips(_schedule, day, dict(pos), per_class)


@st.cache_data
def get_buildings() -> pd.DataFrame:
    return cd.load_buildings()


@st.cache_data
def read_schedule(path: str):
    sched, warns = cd.normalize_schedule(pd.read_csv(path, dtype=str))
    return cd.attach_departments(sched), warns


THEMES = {
    "Dark": {"map": "dark", "idle": [74, 88, 116], "other": [52, 60, 78], "unnamed": [42, 48, 62],
             "text": [235, 240, 250, 255], "label_bg": [14, 18, 28, 215], "tip_bg": "#10151f", "tip_fg": "#e8edf7",
             "line": [150, 165, 200, 70]},
    "Light": {"map": "light", "idle": [176, 188, 210], "other": [214, 220, 232], "unnamed": [224, 228, 237],
              "text": [28, 34, 48, 255], "label_bg": [255, 255, 255, 225], "tip_bg": "#ffffff", "tip_fg": "#1d2433",
              "line": [90, 100, 130, 60]},
    "Streets": {"map": "road", "idle": [150, 168, 200], "other": [205, 212, 226], "unnamed": [218, 223, 233],
                "text": [28, 34, 48, 255], "label_bg": [255, 255, 255, 230], "tip_bg": "#ffffff", "tip_fg": "#1d2433",
                "line": [80, 90, 120, 60]},
}
# teal -> amber -> hot pink: easy to read on dark and light maps
RAMP = [(0.0, (0, 214, 170)), (0.5, (255, 200, 60)), (1.0, (255, 62, 108))]


@st.cache_data(show_spinner=False)
def _room_use_cached(key: str, params: tuple, _schedule, _rooms):
    return en.room_use(_schedule, _rooms, en.Params(*params))


@st.cache_data(show_spinner=False)
def _demand(key: str, day: str, _model, _p, _schedule):
    return en.demand_curve(_schedule, _model, day, _p)


def picked_building(event) -> str | None:
    """Name of the building the user clicked on the map, if any."""
    try:
        objs = event.selection.objects
    except Exception:
        return None
    for layer in ("buildings", "towers"):
        for o in (objs.get(layer) or []):
            if isinstance(o, dict) and o.get("name"):
                return str(o["name"])
    return None


def activity_color(value: float, vmax: float, idle: list[int]) -> list[int]:
    """Muted slate when idle, then teal -> amber -> pink as more classes are in session."""
    if value <= 0 or vmax <= 0:
        return idle + [235]
    t = min(value / vmax, 1.0)
    for (t0, c0), (t1, c1) in zip(RAMP, RAMP[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            return [int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3)] + [250]
    return list(RAMP[-1][1]) + [250]


# ---------------------------------------------------------------- sidebar
buildings = get_buildings()
st.sidebar.title("Campus Activity 3D")
using_real = cd.REAL_PATH.exists()
try:
    schedule, warnings = read_schedule(str(cd.REAL_PATH if using_real else cd.SAMPLE_PATH))
except ValueError as exc:
    st.sidebar.error(str(exc))
    st.stop()
for w in warnings:
    st.sidebar.warning(w)
if using_real:
    st.sidebar.success("Fall 2026 public class schedule (Albion Registrar), start/end times only.")
else:
    st.sidebar.info("Showing SYNTHETIC sample data. Run fetch_schedule.py to load the public Fall 2026 schedule.")

mapping, unmatched = cd.match_buildings(schedule["building"].unique(), buildings["name"].tolist())
if unmatched:
    st.sidebar.warning("Buildings not found on the map: " + ", ".join(unmatched))
schedule = schedule.assign(building=schedule["building"].map(lambda b: mapping.get(b, b)))
data_key = "fall2026" if using_real else "sample"

day = st.sidebar.selectbox("Day", cd.DAYS, index=0)
st.sidebar.markdown("**Display**")
theme_name = st.sidebar.radio("Map style", list(THEMES), horizontal=True)
T = THEMES[theme_name]
eparams = energy_view.sidebar_params(sorted(schedule["building"].unique()))
map_metric = st.sidebar.radio(
    "Map shows", ["Classes in session", "Electricity demand now (kW, modeled)", "Heating share (month, modeled)"])
heat_month = st.sidebar.selectbox("Month for heating", en.MONTHS, index=0,
                                  disabled=not map_metric.startswith("Heating"))
elevation_mode = st.sidebar.radio(
    "Building height", ["Real height + activity tower", "Scale height by activity"], index=0)
tower_scale = st.sidebar.slider("Activity tower height (m per class)", 3, 40, 14)
show_labels = st.sidebar.checkbox("Building names", True)
label_all = st.sidebar.checkbox("Label every named building", False)
show_flows = st.sidebar.checkbox("Estimated movement arcs", False)
st.sidebar.markdown("**Walking between classes (simulated)**")
show_walkers = st.sidebar.checkbox("Show walkers", True)
walker_style = st.sidebar.radio("Walker style", ["People", "Dots"], horizontal=True)
per_class = st.sidebar.slider("Walkers per class (illustration)", 1, 40, 10)
group_by = st.sidebar.selectbox("Color walkers by", ["Department they are walking to", "Building they leave", "Building they go to"])
play_speed = st.sidebar.select_slider("Play speed (sim minutes per second)", [5, 10, 15, 30, 60], value=15)
st.sidebar.caption(
    "Counts are classes in session, not people. The walkers are an ILLUSTRATION: no real student data exists, so "
    "each class that ends sends a fixed number of figures toward a class starting within 15 minutes. "
    "Floors are guessed from "
    "room numbers. Map data (c) OpenStreetMap contributors.")

# ---------------------------------------------------------------- state
if "focus" not in st.session_state:
    st.session_state.focus = None
if "map_reset" not in st.session_state:
    st.session_state.map_reset = 0
if "last_pick" not in st.session_state:
    st.session_state.last_pick = None
focus = st.session_state.focus or "(whole campus)"
if "playing" not in st.session_state:
    st.session_state.playing = False
if "minute" not in st.session_state:
    st.session_state.minute = 9 * 60
if "selected" not in st.session_state:
    st.session_state.selected = None

st.title("Campus Activity and Energy 3D")
c1, c2, c3, c4 = st.columns([1, 1, 2, 4])
if c1.button("Pause" if st.session_state.playing else "Play", width="stretch"):
    st.session_state.playing = not st.session_state.playing
    st.rerun()
if c2.button("Reset", width="stretch"):
    st.session_state.minute = 8 * 60
    st.session_state.playing = False
    st.rerun()
if focus != "(whole campus)":
    if c3.button("Back to whole campus", width="stretch"):
        st.session_state.focus = None
        st.session_state.last_pick = None
        st.session_state.map_reset += 1      # new map widget = cleared click selection
        st.rerun()
else:
    c3.caption("Click a building to open its floors.")

curve = cd.campus_curve(schedule, day, STEP)
named = buildings[buildings["name"] != ""].copy()
pos_map = {r["name"]: (float(r["lon"]), float(r["lat"])) for _, r in named.iterrows()}
trips = get_trips(schedule, data_key, day, per_class,
                  tuple(sorted(pos_map.items())))
interval = timedelta(seconds=0.5) if st.session_state.playing else None


@st.fragment(run_every=interval)
def live_view():
    # advance the clock before the slider widget is created in this run
    if st.session_state.playing:
        base = max(int(round(play_speed * 0.5)), 1)
        slow = cd.anyone_walking(trips, st.session_state.minute) if show_walkers else False
        nxt = st.session_state.minute + (1 if slow else base)  # slow-motion while people are walking
        st.session_state.minute = nxt if nxt <= cd.DAY_END_MIN else cd.DAY_START_MIN
    minute = st.select_slider(
        "Time of day", options=list(range(cd.DAY_START_MIN, cd.DAY_END_MIN + 1, CLOCK_STEP)), key="minute",
        format_func=cd.fmt_time, label_visibility="collapsed")
    st.markdown(f"### {day} {cd.fmt_time(minute)}")

    act = cd.activity_by_building(schedule, day, minute)
    counts = dict(zip(act["building"], act["classes"]))
    rooms = dict(zip(act["building"], act["rooms"]))
    labels = dict(zip(act["building"], act["labels"]))
    vmax = max(int(curve["classes"].max()), 1)
    bmax = max(max(counts.values(), default=1), 1)

    scheduled = set(schedule["building"].unique())
    _p = en.Params(*eparams)
    _model, _mm, _rooms = energy_view._compute(buildings, schedule, data_key, eparams)
    kw_by = en.live_power_kw(_model, rooms, _p).to_dict()    # demand follows ROOMS in use (sections sharing a room count once)
    # modeled demand of each classroom while its class runs, shown next to the class in the hover
    _use_rooms = _room_use_cached(data_key, eparams, schedule, _rooms)
    _kw_room = {(r.building, r.room): float(r.kw_in_use) for r in _use_rooms.itertuples()}
    _kwh_term_room = {(r.building, r.room): float(r.kwh_in_use_term) for r in _use_rooms.itertuples()}

    def _class_label(r) -> str:
        kwr = _kw_room.get((r["building"], r["room"] or "(room not listed)"))
        code = str(r["course_code"] or "?") + (f'-{r["section"]}' if str(r.get("section") or "") else "")
        title = f' {r["course_title"]}' if str(r.get("course_title") or "") else ""
        base_txt = f'{code}{title} ({r["room"]})' if r["room"] else f"{code}{title}"
        cr = pd.to_numeric(r.get("credit_hours"), errors="coerce")
        parts = []
        if str(r.get("department") or ""):
            parts.append(str(r["department"]))
        if pd.notna(cr):
            parts.append(f"{cr:g} credit hrs")
        if kwr is not None:
            parts.append(f"{kwr:.1f} kW now")
            term = _kwh_term_room.get((r["building"], r["room"] or "(room not listed)"))
            if term is not None:
                parts.append(f"{term:,.0f} kWh this term")
        return base_txt + (": " + ", ".join(parts) if parts else "")

    _now_rows = cd.in_session(schedule, day, minute)
    labels = {}
    for _bname, _grp in _now_rows.groupby("building"):
        _items = [_class_label(r) for _, r in _grp.iterrows()]
        labels[_bname] = "<br/>".join(_items[:8]) + (f"<br/>+{len(_items) - 8} more" if len(_items) > 8 else "")
    heat_by = (_mm[_mm["month_name"] == heat_month].set_index("name")["heat"] * 100).to_dict()
    modeled = set(_model["name"])

    if map_metric.startswith("Classes"):
        values, colored, unit_txt = counts, scheduled, "classes"
    elif map_metric.startswith("Electricity"):
        values, colored, unit_txt = kw_by, modeled, "kW"
    else:
        values, colored, unit_txt = heat_by, modeled, f"% of annual campus heating in {heat_month}"

    df = buildings.copy()
    df["classes"] = df["name"].map(counts).fillna(0).astype(int)
    df["rooms"] = df["name"].map(rooms).fillna(0).astype(int)
    df["detail"] = df["name"].map(labels).fillna("")
    df["mval"] = df["name"].map(values).fillna(0.0).astype(float)
    mmax = max(float(df["mval"].max()), 1e-9)
    unit_h = max(bmax, 5) * tower_scale          # tower height of the busiest building, same scale in every mode
    df["kw_txt"] = df["name"].map(kw_by).map(lambda v: "" if pd.isna(v) else f"{v:,.0f} kW (modeled)")
    _bsum = en.building_rooms_summary(_rooms, _model).set_index("building")
    df["rooms_txt"] = df["name"].map(lambda n: "" if n not in _bsum.index else (
        f"{int(_bsum.loc[n, 'classrooms'])} classrooms in this term's schedule, together about "
        f"{_bsum.loc[n, 'classroom_kwh_year']:,.0f} kWh per year ({_bsum.loc[n, 'classroom_share']:.0%} of the building)"))
    _year = _model.set_index("name")["elec_kwh_year"].to_dict()
    df["elec_txt"] = df["name"].map(_year).map(lambda v: "" if pd.isna(v) else f"{v:,.0f} kWh per year, about ${v * 0.1401:,.0f} (modeled)")
    df["heat_txt"] = df["name"].map(heat_by).map(
        lambda v: "" if pd.isna(v) else f"{v:.2f}% of annual campus heating in {heat_month} (modeled)")

    def paint(row):
        if row["name"] in colored:
            return activity_color(row["mval"], mmax, T["idle"])
        return (T["other"] if row["name"] else T["unnamed"]) + [215 if row["name"] else 170]

    df["color"] = df.apply(paint, axis=1)
    focused = focus != "(whole campus)"
    if focused:
        ghost = df["name"] == focus
        df.loc[ghost, "color"] = df.loc[ghost, "color"].map(lambda c: c[:3] + [38])
    real_mode = elevation_mode.startswith("Real")
    if real_mode:
        df["elev"] = df["height_m"].clip(lower=6) * 1.15
    else:
        df["elev"] = df["height_m"] * 0.3 + df["mval"] / mmax * unit_h
    df["label_name"] = df["name"].replace("", "(building)")
    material = {"ambient": 0.55, "diffuse": 0.65, "shininess": 40, "specularColor": [70, 76, 90]}

    layers = [pdk.Layer(
        "PolygonLayer", df, id="buildings", get_polygon="polygon", get_fill_color="color", get_line_color=T["line"],
        get_elevation="elev", extruded=True, wireframe=False, stroked=False, pickable=True,
        auto_highlight=True, highlight_color=[255, 255, 255, 70], material=material)]

    if real_mode:
        towers = df[(df["mval"] > 0) & df["name"].isin(colored) & (df["name"] != focus)].copy()
        if not towers.empty:
            towers["tower"] = towers["mval"] / mmax * unit_h
            towers["pos3"] = towers.apply(lambda r: [r["lon"], r["lat"], float(r["elev"])], axis=1)
            towers["tcolor"] = towers["color"].map(lambda c: c[:3] + [215])
            layers.append(pdk.Layer(
                "ColumnLayer", towers, id="towers", get_position="pos3", get_elevation="tower", radius=4.5, disk_resolution=24,
                get_fill_color="tcolor", extruded=True, pickable=True, material=material))

    if show_labels:
        lab = df[df["name"] != ""].copy()
        if map_metric.startswith("Classes"):
            if not label_all:
                lab = lab[lab["name"].isin(scheduled)]
        else:
            lab = lab[lab["name"].isin(colored)].sort_values("mval", ascending=False).head(12)
        lab["z"] = lab["elev"] + (lab["mval"] / mmax * unit_h if real_mode else 0) + 6

        def label_text(r):
            if map_metric.startswith("Classes"):
                return f'{r["name"]}  {int(r["mval"])}' if r["mval"] else r["name"]
            if map_metric.startswith("Electricity"):
                return f'{r["name"]}  {r["mval"]:,.0f} kW'
            return f'{r["name"]}  {r["mval"]:.1f}%'

        lab["text"] = lab.apply(label_text, axis=1)
        layers.append(pdk.Layer(
            "TextLayer", lab, get_position=["lon", "lat", "z"], get_text="text", get_size=12,
            get_color=T["text"], billboard=True, background=True, get_background_color=T["label_bg"],
            background_padding=[5, 2], font_family='"Segoe UI", Arial, sans-serif', font_weight=600,
            get_text_anchor="'middle'", get_alignment_baseline="'bottom'", pickable=False))

    view_state = pdk.ViewState(latitude=42.2433, longitude=-84.7425, zoom=16.6, pitch=52, bearing=-24)
    if focused:
        feats = df[df["name"] == focus]
        n_floors = int(_model.loc[_model["name"] == focus, "floors"].max()) if (_model["name"] == focus).any() \
            else int(max(1, round(float(feats["height_m"].max()) / 3.5)))
        now_b = cd.in_session(schedule, day, minute)
        now_b = now_b[now_b["building"] == focus].copy()
        now_b["floor"] = now_b["floor"].clip(lower=1).clip(upper=n_floors)
        now_b["label"] = now_b.apply(_class_label, axis=1)
        per_floor = now_b.groupby("floor").agg(
            classes=("room", "size"), rooms=("room", "nunique"),
            detail=("label", lambda x: "<br/>".join(list(x)[:6])))
        b_total = float(counts.get(focus, 0))
        b_kw = float(kw_by.get(focus, 0.0))
        b_heat = float(heat_by.get(focus, 0.0))
        rows = []
        for f in range(1, n_floors + 1):
            c = int(per_floor["classes"].get(f, 0))
            if map_metric.startswith("Classes"):
                v, vmax_f = float(c), float(max(bmax, 3))
            elif map_metric.startswith("Electricity"):
                share = (0.5 / n_floors + 0.5 * c / b_total) if b_total > 0 else 1.0 / n_floors
                v = b_kw * share
                vmax_f = mmax / n_floors
            else:
                v, vmax_f = b_heat / n_floors, mmax / n_floors
            rows.append({"floor": f, "classes": c, "rooms": int(per_floor["rooms"].get(f, 0)),
                         "detail": str(per_floor["detail"].get(f, "")), "value": v,
                         "vmax": max(vmax_f, 1e-9)})
        slab_rows = []
        floor_h, thick = 5.0, 1.4
        for _, feat in feats.iterrows():
            ring = feat["polygon"][0]
            for fr in rows:
                z0 = (fr["floor"] - 1) * floor_h + 0.5
                col = activity_color(fr["value"], fr["vmax"], T["idle"])
                slab_rows.append({
                    "poly3": [[p[0], p[1], z0] for p in ring], "slab_h": thick, "color": col,
                    "label_name": f"{focus}, floor {fr['floor']}", "classes": fr["classes"], "rooms": fr["rooms"],
                    "detail": fr["detail"],
                    "kw_txt": "(whole building: %s)" % df.loc[df["name"] == focus, "kw_txt"].iloc[0],
                    "heat_txt": "", "elec_txt": df.loc[df["name"] == focus, "elec_txt"].iloc[0],
                    "rooms_txt": df.loc[df["name"] == focus, "rooms_txt"].iloc[0], "lon": feat["lon"], "lat": feat["lat"], "z": z0 + thick + 1.5,
                    "text": f"Floor {fr['floor']}: " + (f"{fr['classes']} class(es)" if fr["classes"] else "no class"),
                })
        slabs = pd.DataFrame(slab_rows)
        layers.append(pdk.Layer(
            "PolygonLayer", slabs, get_polygon="poly3", get_fill_color="color", get_elevation="slab_h",
            extruded=True, wireframe=False, stroked=False, pickable=True, auto_highlight=True,
            highlight_color=[255, 255, 255, 80], material=material))
        layers.append(pdk.Layer(
            "TextLayer", slabs.drop_duplicates("text").assign(
                lon=feats["lon"].mean(), lat=feats["lat"].mean()),
            get_position=["lon", "lat", "z"], get_text="text", get_size=12, get_color=T["text"], billboard=True,
            background=True, get_background_color=T["label_bg"], background_padding=[5, 2],
            font_family='"Segoe UI", Arial, sans-serif', font_weight=600, get_text_anchor="'middle'",
            get_alignment_baseline="'bottom'", pickable=False))
        view_state = pdk.ViewState(latitude=float(feats["lat"].mean()), longitude=float(feats["lon"].mean()),
                                   zoom=18.4, pitch=60, bearing=-24)

    walking = cd.walkers_at(trips, minute) if show_walkers else cd.walkers_at(trips.iloc[0:0], minute)
    legend_items: list[tuple[str, list[int]]] = []
    if show_walkers and not walking.empty:
        key_col = {"Department they are walking to": "dept", "Building they leave": "from_b",
                   "Building they go to": "to_b"}[group_by]
        order = trips[key_col].value_counts().index.tolist()          # stable colours for the whole day
        color_of = {g: GROUP_COLORS[i % len(GROUP_COLORS)] for i, g in enumerate(order)}
        walking["color"] = walking[key_col].map(lambda g: color_of[g] + [255])
        walking["alt"] = 3.0
        present = walking[key_col].value_counts()
        legend_items = [(g, color_of[g]) for g in present.index]
        if walker_style == "People":
            icon = {"url": person_icon_url(), "width": 48, "height": 64, "anchorY": 64, "mask": True}
            walking["icon_data"] = [icon] * len(walking)
            layers.append(pdk.Layer(
                "IconLayer", walking, get_icon="icon_data", get_position=["lon", "lat", "alt"], get_size=30,
                size_scale=1, get_color="color", pickable=False, billboard=True))
        else:
            layers.append(pdk.Layer(
                "ScatterplotLayer", walking, get_position=["lon", "lat", "alt"], get_fill_color="color",
                get_radius=3.2, radius_min_pixels=3, radius_max_pixels=9, pickable=False, stroked=True,
                get_line_color=[255, 255, 255, 220], line_width_min_pixels=1))
    if show_flows:
        tr = cd.transitions(schedule, day, minute)
        if not tr.empty:
            pos = named.set_index("name")[["lon", "lat"]]
            tr = tr[tr["from_building"].isin(pos.index) & tr["to_building"].isin(pos.index)].copy()
            if not tr.empty:
                tr["src"] = tr["from_building"].map(lambda b: [pos.loc[b, "lon"], pos.loc[b, "lat"], 4])
                tr["dst"] = tr["to_building"].map(lambda b: [pos.loc[b, "lon"], pos.loc[b, "lat"], 4])
                layers.append(pdk.Layer(
                    "ArcLayer", tr, get_source_position="src", get_target_position="dst",
                    get_width="pairs * 1.5", get_source_color=[80, 200, 255, 190], get_target_color=[255, 110, 160, 220],
                    width_min_pixels=2, get_height=0.6, pickable=False))
                st.caption(f"{int(tr['pairs'].sum())} possible class-to-class moves in progress "
                           f"(between {len(tr)} building pairs)")

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style=T["map"],
        tooltip={"html": "<b>{label_name}</b><br/>Classes in session: {classes}<br/>Rooms in use: {rooms}<br/><i>class (room): credit hours, modeled kW now, kWh this term</i><br/>{detail}<br/>Electric demand now: {kw_txt}<br/>Whole building electricity: {elec_txt}<br/>Classrooms: {rooms_txt}<br/>Heating: {heat_txt}",
                 "style": {"backgroundColor": T["tip_bg"], "color": T["tip_fg"], "fontFamily": "Segoe UI, Arial",
                           "borderRadius": "6px", "padding": "8px 10px", "maxWidth": "360px"}},
    )
    event = st.pydeck_chart(deck, height=600, on_select="rerun", selection_mode="single-object",
                            key=f"map_{st.session_state.map_reset}")
    name = picked_building(event)
    if name and name != st.session_state.last_pick:
        st.session_state.last_pick = name
        if name != st.session_state.focus:
            st.session_state.focus = name
            st.rerun(scope="app")
    energy_view.attribution()
    if show_walkers:
        if legend_items:
            chips = " ".join(
                f'<span style="display:inline-block;margin:2px 10px 2px 0;font-size:13px">'
                f'<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:rgb({c[0]},{c[1]},{c[2]});'
                f'margin-right:5px"></span>{g}</span>' for g, c in legend_items[:14])
            st.markdown(f"**Walking now (simulated): {len(walking)}**  \n{chips}", unsafe_allow_html=True)
        else:
            st.caption("Nobody is walking between classes at this time. Press Play to watch the class changes.")

    k1, k2, k3, k4, k5 = st.columns(5)
    total = int(sum(counts.values()))
    k1.metric("Classes in session", total)
    k2.metric("Buildings in use", sum(1 for v in counts.values() if v))
    busiest = max(counts, key=counts.get) if counts else "-"
    k3.metric("Busiest building", busiest, counts.get(busiest, 0))
    k4.metric("Peak today", f"{int(curve['classes'].max())} classes",
              cd.fmt_time(int(curve.loc[curve['classes'].idxmax(), 'minute'])))

    _defaults = eparams
    _model, _mm, _rooms = energy_view._compute(buildings, schedule, data_key, _defaults)
    _kw = en.live_power_kw(_model, rooms, en.Params(*_defaults))
    k5.metric("Est. electric demand now", f"{_kw.sum():,.0f} kW", "modeled, not metered", delta_color="off")

    chart_df = curve.assign(now=curve["minute"].between(minute - STEP, minute))
    base = alt.Chart(chart_df).encode(x=alt.X("minute:Q", title=None, axis=alt.Axis(
        values=list(range(cd.DAY_START_MIN, cd.DAY_END_MIN + 1, 120)),
        labelExpr="timeFormat(datum.value * 60000 + 21600000, '%-I %p')")))
    line = base.mark_area(opacity=0.35, line=True).encode(y=alt.Y("classes:Q", title="Classes in session"))
    rule = alt.Chart(pd.DataFrame({"minute": [minute]})).mark_rule(color="#d9363e", size=2).encode(x="minute:Q")
    cl, cr = st.columns(2)
    cl.markdown("**Classes in session**")
    cl.altair_chart((line + rule).properties(height=170), width="stretch")
    dc = _demand(data_key, day, _model, _p, schedule)
    dline = alt.Chart(dc).mark_area(opacity=0.35, line=True, color="#f2a03d").encode(
        x=alt.X("minute:Q", title=None, axis=alt.Axis(
            values=list(range(cd.DAY_START_MIN, cd.DAY_END_MIN + 1, 120)),
            labelExpr="timeFormat(datum.value * 60000 + 21600000, '%-I %p')")),
        y=alt.Y("kw:Q", title="Estimated demand (kW)", scale=alt.Scale(zero=False)))
    cr.markdown("**Estimated electric demand (modeled)**")
    cr.altair_chart((dline + rule).properties(height=170), width="stretch")

    st.markdown("**Building detail**")
    sel = focus
    if sel == "(whole campus)":
        st.caption("Click a building on the map to see it as a stack of floors and to see its classrooms. "
                   "Floors are estimated from OpenStreetMap floor counts and room numbers.")
    if sel != "(whole campus)":
        fa = cd.floor_activity(schedule, sel, day, minute)
        total_b = int(counts.get(sel, 0))
        st.write(f"**{sel}**: {total_b} class(es) in session now; {int(rooms.get(sel, 0))} room(s) in use.")
        if not fa.empty:
            fa["floor"] = fa["floor"].map(lambda f: "Basement" if f == 0 else f"Floor {f}")
            st.bar_chart(fa.set_index("floor")["classes"], height=160)
        today = schedule[(schedule["building"] == sel) & (schedule["meeting_day"] == day)].sort_values("start_min")
        if not today.empty:
            show = today[["start_min", "end_min", "room", "course_code", "section", "course_title"]].copy()
            show["start"] = show["start_min"].map(cd.fmt_time)
            show["end"] = show["end_min"].map(cd.fmt_time)
            show["now"] = (today["start_min"] <= minute) & (minute < today["end_min"])
            st.dataframe(show[["start", "end", "room", "course_code", "section", "course_title", "now"]], hide_index=True, height=220)

        rl = en.room_live(schedule, _rooms, sel, day, minute, _p)
        if sel in _bsum.index:
            _r = _bsum.loc[sel]
            st.write(f"**{sel}: {int(_r['classrooms'])} classrooms in this term's schedule.** Together they use about "
                     f"**{_r['classroom_kwh_year']:,.0f} kWh a year** (modeled), which is {_r['classroom_share']:.0%} of the building's "
                     f"{_r['building_kwh_year']:,.0f} kWh. Only rooms that appear in the Fall 2026 schedule are counted; rooms not "
                     "scheduled this term are not known.")
        st.markdown("**Estimated electricity per classroom (modeled, not metered)**")
        if rl.empty:
            st.caption("No rooms are listed for this building in the schedule.")
        else:
            rs = rl[["room", "in_session_now", "kw_now", "class_hours_today", "kwh_today", "elec_kwh_year_room"]].copy()
            rs.columns = ["Room", "In session now", "Demand now (kW)", "Class hours today", "Energy today (kWh)",
                          "Energy per year (kWh)"]
            st.dataframe(rs.round(2), hide_index=True, height=240)
            st.caption("Each room = its building's electricity per m2 x a typical classroom area (an assumption you can change), "
                       "weighted by how much it is scheduled. Albion publishes no room-level meter data, so use the values to "
                       "compare rooms, not as measurements. Assumptions and sources: see the panel below.")


live_view()
st.divider()
energy_view.render_details(buildings, schedule, data_key, eparams,
                           None if focus == "(whole campus)" else focus)
energy_view.sources_panel()
