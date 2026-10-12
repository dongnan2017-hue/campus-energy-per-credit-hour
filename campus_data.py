"""Data layer for the campus activity visual: buildings, schedule loading, activity maths.

Counts are CLASSES IN SESSION (public start/end times only), not people.
"""
from __future__ import annotations

import difflib
import html
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
DAY_FROM_LETTER = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri"}
DAY_FROM_NAME = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri"}
DAY_START_MIN = 7 * 60
DAY_END_MIN = 22 * 60

BUILDINGS_PATH = Path(__file__).parent / "data" / "buildings.geojson"
SAMPLE_PATH = Path(__file__).parent / "data" / "course_meetings_sample.csv"
DEPT_LINK_PATH = Path(__file__).parent / "data" / "section_department_link.csv"
REAL_PATH = Path(__file__).parent / "data" / "202630_meetings.csv"   # Fall 2026, from fetch_schedule.py

# Registrar building names -> OpenStreetMap names (edit freely; unmatched names are shown in the app)
BUILDING_ALIASES = {
    "kresge science bldg": "Kresge Hall",
    "herrick speech and theater": "Herrick Center",
    "astronomical observatory": "Observatory",
}


# ----------------------------------------------------------------------------- buildings
def load_buildings(path: Path = BUILDINGS_PATH) -> pd.DataFrame:
    """One row per OSM building: name, height_m, polygon ring, centroid."""
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for f in gj["features"]:
        ring = f["geometry"]["coordinates"][0]
        lon = sum(p[0] for p in ring[:-1]) / max(len(ring) - 1, 1)
        lat = sum(p[1] for p in ring[:-1]) / max(len(ring) - 1, 1)
        p = f["properties"]
        rows.append({
            "osm_id": p["osm_id"], "name": p["name"], "kind": p["building"],
            "levels": p["levels"], "height_m": p["height_m"],
            "polygon": [ring], "lon": lon, "lat": lat,
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- schedule
def _parse_time(value) -> int | None:
    """'09:00', '9:00 AM', '0900', datetime.time -> minutes after midnight."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "hour"):
        return value.hour * 60 + value.minute
    s = str(value).strip().upper().replace(".", "")
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})(?::\d{2})?\s*([AP]M)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return h * 60 + mi if h < 24 and mi < 60 else None


def _expand_days(value) -> list[str]:
    s = str(value).strip()
    if re.fullmatch(r"[MTWRFmtwrf]{1,5}", s) and s.lower() not in DAY_FROM_NAME and len(s) > 0:
        return [DAY_FROM_LETTER[c.upper()] for c in s]
    key = s[:3].lower()
    return [DAY_FROM_NAME[key]] if key in DAY_FROM_NAME else []


def normalize_schedule(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Validate/clean a schedule. Required: building, meeting_day, start_time, end_time.
    Optional: room, course_code, crn. Returns (clean_df, warnings)."""
    warnings: list[str] = []
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in ("building", "meeting_day", "start_time", "end_time") if c not in df.columns]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing))
    for col in ("room", "course_code", "crn", "course_title", "section", "subject_desc"):
        if col not in df.columns:
            df[col] = ""
    df["building"] = df["building"].astype(str).map(html.unescape).str.strip()
    df["room"] = df["room"].fillna("").astype(str).str.strip()

    df["start_min"] = df["start_time"].map(_parse_time)
    df["end_min"] = df["end_time"].map(_parse_time)
    bad = df["start_min"].isna() | df["end_min"].isna() | (df["end_min"] <= df["start_min"])
    if bad.any():
        warnings.append(f"Dropped {int(bad.sum())} row(s) with unreadable or inverted times.")
        df = df[~bad]

    df["meeting_day"] = df["meeting_day"].map(_expand_days)
    nodays = df["meeting_day"].map(len) == 0
    if nodays.any():
        warnings.append(f"Dropped {int(nodays.sum())} row(s) with unrecognised or weekend days.")
        df = df[~nodays]
    df = df.explode("meeting_day").reset_index(drop=True)
    df["floor"] = df["room"].map(floor_of)
    return df, warnings


def attach_departments(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `department`: the department group for each section when a link file is present, else the Registrar subject name."""
    df = df.copy()
    fallback = df["subject_desc"].where(df["subject_desc"].astype(str) != "", df["course_code"].astype(str).str.split().str[0])
    if DEPT_LINK_PATH.exists():
        link = pd.read_csv(DEPT_LINK_PATH, dtype=str).drop_duplicates("crn").set_index("crn")["department_group"]
        df["department"] = df["crn"].map(link).fillna("")
        df["department"] = df["department"].where(df["department"] != "", fallback)
    else:
        df["department"] = fallback
    return df


def floor_of(room: str) -> int:
    """Guess the floor from a room number: 204 -> 2, 'B12' -> 0 (basement), 1010 -> 10."""
    r = str(room).strip().upper()
    if r.startswith(("B", "LL")):
        return 0
    m = re.search(r"\d+", r)
    if not m:
        return 1
    digits = m.group(0)
    if len(digits) <= 2:
        return 1
    return int(digits[:-2])


def match_buildings(schedule_names, osm_names, cutoff: float = 0.72) -> tuple[dict, list[str]]:
    """Map schedule building names to OSM names (case-insensitive, then fuzzy)."""
    lookup = {n.lower(): n for n in osm_names if n}
    mapping, unmatched = {}, []
    for name in sorted(set(schedule_names)):
        low = name.lower().strip()
        alias = BUILDING_ALIASES.get(low)
        if alias and alias.lower() in lookup:
            mapping[name] = lookup[alias.lower()]
            continue
        if low in lookup:
            mapping[name] = lookup[low]
            continue
        # 'Palenske' -> 'Palenske Hall'
        starts = [orig for l, orig in lookup.items() if l.startswith(low) or low.startswith(l)]
        if len(starts) == 1:
            mapping[name] = starts[0]
            continue
        close = difflib.get_close_matches(low, list(lookup), n=1, cutoff=cutoff)
        if close:
            mapping[name] = lookup[close[0]]
        else:
            unmatched.append(name)
    return mapping, unmatched


# ----------------------------------------------------------------------------- activity maths
def in_session(schedule: pd.DataFrame, day: str, minute: int) -> pd.DataFrame:
    s = schedule
    return s[(s["meeting_day"] == day) & (s["start_min"] <= minute) & (minute < s["end_min"])]


def activity_by_building(schedule: pd.DataFrame, day: str, minute: int) -> pd.DataFrame:
    now = in_session(schedule, day, minute)
    if now.empty:
        return pd.DataFrame(columns=["building", "classes", "rooms", "labels"])
    g = now.groupby("building")
    return pd.DataFrame({
        "classes": g.size(),
        "rooms": g["room"].nunique(),
        "labels": g.apply(lambda x: ", ".join(
            f"{(c if c else '?')} ({r})" if r else str(c or "?")
            for c, r in zip(x["course_code"].astype(str), x["room"])), include_groups=False),
    }).reset_index()


def campus_curve(schedule: pd.DataFrame, day: str, step: int = 5) -> pd.DataFrame:
    minutes = list(range(DAY_START_MIN, DAY_END_MIN + 1, step))
    d = schedule[schedule["meeting_day"] == day]
    counts = [int(((d["start_min"] <= m) & (m < d["end_min"])).sum()) for m in minutes]
    return pd.DataFrame({"minute": minutes, "classes": counts, "time": [fmt_time(m) for m in minutes]})


def floor_activity(schedule: pd.DataFrame, building: str, day: str, minute: int) -> pd.DataFrame:
    now = in_session(schedule, day, minute)
    now = now[now["building"] == building]
    out = now.groupby("floor").size().rename("classes").reset_index()
    return out.sort_values("floor")


def transitions(schedule: pd.DataFrame, day: str, minute: int, max_gap: int = 15) -> pd.DataFrame:
    """Estimated walking between buildings: a class ended in A and one starts in B within max_gap
    minutes, and `minute` lies between the two times. A relative flow strength, not a headcount."""
    d = schedule[schedule["meeting_day"] == day]
    left = d[(d["end_min"] <= minute) & (d["end_min"] >= minute - max_gap)][["building", "end_min"]]
    right = d[(d["start_min"] >= minute) & (d["start_min"] <= minute + max_gap)][["building", "start_min"]]
    if left.empty or right.empty:
        return pd.DataFrame(columns=["from_building", "to_building", "pairs"])
    pairs = left.merge(right, how="cross", suffixes=("_from", "_to"))
    pairs = pairs[(pairs["building_from"] != pairs["building_to"])
                  & (pairs["start_min"] - pairs["end_min"] <= max_gap)
                  & (pairs["start_min"] >= pairs["end_min"])]
    if pairs.empty:
        return pd.DataFrame(columns=["from_building", "to_building", "pairs"])
    out = pairs.groupby(["building_from", "building_to"]).size().rename("pairs").reset_index()
    return out.rename(columns={"building_from": "from_building", "building_to": "to_building"})


def fmt_time(minute: int) -> str:
    h, m = divmod(int(minute), 60)
    ap = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {ap}"


# ----------------------------------------------------------------------------- simulated walkers
def build_trips(schedule: pd.DataFrame, day: str, pos: dict, per_class: int = 10,
                max_gap: int = 15, seed: int = 7) -> pd.DataFrame:
    """SIMULATED walking between classes. There is no data about real students, so for every class that
    ends we pick the class starting next (within max_gap minutes) at random and send `per_class`
    illustrative walkers to that building. Group = department (course prefix) of the class they are walking to.
    """
    d = schedule[(schedule["meeting_day"] == day) & schedule["building"].isin(pos)].reset_index(drop=True)
    rng = np.random.default_rng(seed + DAYS.index(day))
    starts = d.groupby("start_min")
    rows = []
    start_keys = np.array(sorted(d["start_min"].unique()))
    for _, a in d.iterrows():
        cand_keys = start_keys[(start_keys >= a["end_min"]) & (start_keys <= a["end_min"] + max_gap)]
        if len(cand_keys) == 0:
            continue
        key = int(rng.choice(cand_keys))
        grp = starts.get_group(key)
        b = grp.iloc[int(rng.integers(len(grp)))]
        if b["building"] == a["building"]:
            continue  # stays put
        rows.append((int(a["end_min"]), key, a["building"], b["building"],
                     str(b["department"]) if "department" in b.index and str(b["department"]) else (str(b["course_code"]).split(" ")[0] or "?")))
    if not rows:
        return pd.DataFrame(columns=["depart", "arrive", "lon0", "lat0", "lon1", "lat1",
                                     "off_lon", "off_lat", "dept", "from_b", "to_b"])
    t = pd.DataFrame(rows, columns=["end_min", "start_min", "from_b", "to_b", "dept"])
    t = t.loc[t.index.repeat(per_class)].reset_index(drop=True)
    n = len(t)
    lon0 = t["from_b"].map(lambda b: pos[b][0]).to_numpy()
    lat0 = t["from_b"].map(lambda b: pos[b][1]).to_numpy()
    lon1 = t["to_b"].map(lambda b: pos[b][0]).to_numpy()
    lat1 = t["to_b"].map(lambda b: pos[b][1]).to_numpy()
    mx = (lon1 - lon0) * np.cos(np.radians(lat0)) * 111320.0
    my = (lat1 - lat0) * 110574.0
    dist = np.hypot(mx, my) + 1.0
    depart = t["end_min"].to_numpy() + rng.uniform(0.3, 2.5, n)
    speed = rng.uniform(70, 95, n)                       # metres per minute (~4-5.7 km/h)
    arrive = np.minimum(depart + dist / speed, t["start_min"].to_numpy() - 0.2)
    arrive = np.maximum(arrive, depart + 0.5)
    side = rng.normal(0, 6, n)                           # lateral spread so walkers do not stack, metres
    nx, ny = -my / dist, mx / dist                       # unit vector perpendicular to the path
    return pd.DataFrame({
        "depart": depart, "arrive": arrive, "lon0": lon0, "lat0": lat0, "lon1": lon1, "lat1": lat1,
        "off_lon": side * nx / (111320.0 * np.cos(np.radians(lat0))), "off_lat": side * ny / 110574.0,
        "dept": t["dept"].to_numpy(), "from_b": t["from_b"].to_numpy(), "to_b": t["to_b"].to_numpy(),
    })


def walkers_at(trips: pd.DataFrame, minute: float) -> pd.DataFrame:
    """Positions of everyone walking at `minute` (fractional minutes allowed)."""
    if trips.empty:
        return trips.assign(lon=[], lat=[])
    w = trips[(trips["depart"] <= minute) & (trips["arrive"] >= minute)].copy()
    if w.empty:
        return w.assign(lon=[], lat=[])
    f = ((minute - w["depart"]) / (w["arrive"] - w["depart"])).clip(0, 1)
    bulge = np.sin(np.pi * f)                            # lateral spread is largest mid-way
    w["lon"] = w["lon0"] + (w["lon1"] - w["lon0"]) * f + w["off_lon"] * bulge
    w["lat"] = w["lat0"] + (w["lat1"] - w["lat0"]) * f + w["off_lat"] * bulge
    return w


def anyone_walking(trips: pd.DataFrame, minute: float) -> bool:
    return (not trips.empty) and bool(((trips["depart"] <= minute) & (trips["arrive"] >= minute)).any())
