#!/usr/bin/env python3
"""
Hevy Training Dashboard — Backend
──────────────────────────────────
Run:   python app.py
Open:  http://localhost:5000

Requirements:
    pip install flask requests pandas numpy python-dotenv

Caching:
    All Hevy API data is saved to cache.json after the first fetch.
    Subsequent page loads read from the file — zero API calls.
    Click "Refresh" in the UI (or POST /api/refresh) to re-fetch.
    Cache also auto-expires after CACHE_MAX_AGE_HOURS hours.
"""

import os, sys, math, json, time
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
import numpy as np
import pandas as pd
import flask
from flask import Flask, jsonify, render_template, request, send_from_directory
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

from hevy_db import (
    init_db,
    get_db,
    insert_workouts,
    insert_templates,
    get_latest_workout_time,
    save_payload,
    load_payload,
)


class NumpyEncoder(json.JSONEncoder):
    """Converts numpy scalar types to native Python so Flask can serialise them."""

    def default(self, o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


class NumpyJSONProvider(flask.json.provider.DefaultJSONProvider):
    """Flask 2.2+ JSON provider that handles numpy types."""

    def dumps(self, obj, **kwargs):
        kwargs.setdefault("cls", NumpyEncoder)
        return super().dumps(obj, **kwargs)


load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY = os.environ.get("HEVY_API_KEY", "").strip()
BASE_URL = "https://api.hevyapp.com/v1"
PAGE_SIZE = 10
TOP_N = 8

FLASK_PORT = int(os.environ.get("FLASK_PORT", "5000"))
FLASK_HOST = os.environ.get("FLASK_HOST", "127.0.0.1")
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() in ("true", "1", "yes")

STALE_DAYS = 21
DELOAD_THRESHOLD = 0.90
UPPER_REP_TARGET = 12
WEIGHT_INCREMENT = 2.0
REP_RESET_AFTER_BUMP = 8

MUSCLE_MAP_FALLBACK = {
    "bench": "Chest",
    "chest fly": "Chest",
    "pec": "Chest",
    "squat": "Legs",
    "lunge": "Legs",
    "leg press": "Legs",
    "leg curl": "Legs",
    "leg extension": "Legs",
    "hack squat": "Legs",
    "deadlift": "Back",
    "barbell row": "Back",
    "dumbbell row": "Back",
    "lat pulldown": "Back",
    "pull-up": "Back",
    "pullup": "Back",
    "chin-up": "Back",
    "chinup": "Back",
    "seated row": "Back",
    "rdl": "Back",
    "shoulder press": "Shoulders",
    "overhead press": "Shoulders",
    "military press": "Shoulders",
    "arnold press": "Shoulders",
    "lateral raise": "Shoulders",
    "front raise": "Shoulders",
    "face pull": "Shoulders",
    "rear delt": "Shoulders",
    "curl": "Biceps",
    "bicep": "Biceps",
    "hammer curl": "Biceps",
    "tricep": "Triceps",
    "triceps": "Triceps",
    "pushdown": "Triceps",
    "skull": "Triceps",
    "calf": "Calves",
    "calves": "Calves",
    "plank": "abdominals",
    "crunch": "abdominals",
    "ab ": "abdominals",
    "sit-up": "abdominals",
}

MUSCLE_NORMALISE = {
    "chest": "Chest",
    "upper_chest": "Chest",
    "lower_chest": "Chest",
    "quadriceps": "Legs",
    "hamstrings": "Legs",
    "glutes": "Legs",
    "adductors": "Legs",
    "abductors": "Legs",
    "hip_flexors": "Legs",
    "calves": "Calves",
    "lats": "Back",
    "upper_back": "Traps",  # upper_back = traps + rhomboids catch-all
    "lower_back": "Back",
    "traps": "Traps",
    "rhomboids": "Traps",
    "shoulders": "Shoulders",
    "front_delts": "Shoulders",
    "side_delts": "Shoulders",
    "rear_delts": "Shoulders",
    "biceps": "Biceps",
    "triceps": "Triceps",
    "forearms": "Forearms",
    "abs": "abdominals",
    "abdominals": "abdominals",
    "obliques": "abdominals",
    "core": "abdominals",
    "neck": "Neck",
}
# Per-exercise secondary muscle weights — (template_id, muscle_raw) → fraction of primary volume
# Default is 0.5 for any secondary not listed here
SECONDARY_WEIGHTS = {
    # ── Romanian Deadlift ────────────────────────────────────────────────────
    # Glutes and lower back are heavily loaded throughout the lift
    ("72CFFAD5", "glutes"): 0.75,
    ("72CFFAD5", "lower_back"): 0.60,
    ("72CFFAD5", "upper_back"): 0.30,
    ("72CFFAD5", "lats"): 0.20,
    # ── Single Leg RDL ───────────────────────────────────────────────────────
    ("937292AB", "glutes"): 0.75,
    ("937292AB", "lower_back"): 0.50,
    # ── Dumbbell Deadlift ────────────────────────────────────────────────────
    # Full posterior chain — glutes and quads genuinely close to primary
    ("5F4E6DD3", "hamstrings"): 0.80,
    ("5F4E6DD3", "quadriceps"): 0.60,
    ("5F4E6DD3", "lower_back"): 0.60,
    ("5F4E6DD3", "upper_back"): 0.35,
    ("5F4E6DD3", "lats"): 0.25,
    ("5F4E6DD3", "traps"): 0.25,
    # ── Bulgarian Split Squat ────────────────────────────────────────────────
    # Glutes genuinely close to primary, hamstrings less so
    ("B5D3A742", "glutes"): 0.70,
    ("B5D3A742", "hamstrings"): 0.40,
    # ── Dumbbell Step Up ─────────────────────────────────────────────────────
    ("BF6ECE89", "glutes"): 0.65,
    ("BF6ECE89", "hamstrings"): 0.35,
    # ── Squat (Dumbbell) ─────────────────────────────────────────────────────
    ("DCFF3E9F", "hamstrings"): 0.45,
    ("DCFF3E9F", "glutes"): 0.60,
    # ── Split Squat ──────────────────────────────────────────────────────────
    ("20C1A3CB", "hamstrings"): 0.40,
    ("20C1A3CB", "glutes"): 0.60,
    # ── Dumbbell Row ─────────────────────────────────────────────────────────
    # Upper back genuinely close to primary, biceps moderate, forearms minimal
    ("F1E57334", "upper_back"): 0.70,
    ("F1E57334", "biceps"): 0.40,
    ("F1E57334", "forearms"): 0.20,
    # ── Bent Over Row ────────────────────────────────────────────────────────
    ("23E92538", "lats"): 0.65,
    ("23E92538", "biceps"): 0.40,
    ("23E92538", "forearms"): 0.20,
    # ── Meadows Row ──────────────────────────────────────────────────────────
    ("C732C341", "lats"): 0.65,
    ("C732C341", "biceps"): 0.40,
    ("C732C341", "forearms"): 0.20,
    # ── Pullover ─────────────────────────────────────────────────────────────
    # Chest genuinely involved, upper_back moderate, triceps minimal
    ("67280085", "chest"): 0.55,
    ("67280085", "upper_back"): 0.40,
    ("67280085", "triceps"): 0.20,
    # ── Incline Bench Press ──────────────────────────────────────────────────
    # Triceps close to primary, shoulders moderate
    ("07B38369", "triceps"): 0.55,
    ("07B38369", "shoulders"): 0.35,
    # ── Bench Press (Dumbbell) ───────────────────────────────────────────────
    ("3601968B", "triceps"): 0.55,
    ("3601968B", "shoulders"): 0.30,
    # ── Floor Press ──────────────────────────────────────────────────────────
    ("756EE329", "triceps"): 0.60,  # triceps extra loaded at lockout
    ("756EE329", "shoulders"): 0.25,
    # ── Push Up ──────────────────────────────────────────────────────────────
    ("392887AA", "triceps"): 0.55,
    ("392887AA", "shoulders"): 0.30,
    # ── Overhead / Shoulder Press ────────────────────────────────────────────
    ("6AC96645", "triceps"): 0.50,
    ("878CD1D0", "triceps"): 0.50,
    # ── Arnold Press ─────────────────────────────────────────────────────────
    ("A69FF221", "triceps"): 0.45,
    # ── Rear Delt Fly ────────────────────────────────────────────────────────
    # Upper back genuinely close to primary for rear delt work
    ("E5988A0A", "upper_back"): 0.60,
    # ── Hip Thrust ───────────────────────────────────────────────────────────
    ("D57C2EC7", "hamstrings"): 0.45,
    ("D57C2EC7", "quadriceps"): 0.30,
    ("D57C2EC7", "adductors"): 0.25,
    # ── Bird Dog ─────────────────────────────────────────────────────────────
    ("BD0AD077", "hamstrings"): 0.40,
    ("BD0AD077", "shoulders"): 0.30,
}


app = Flask(__name__)
app.json_provider_class = NumpyJSONProvider
app.json = NumpyJSONProvider(app)
init_db()

# ── Hevy API ───────────────────────────────────────────────────────────────────


def fetch_new_workouts(known_ids: set) -> list[dict]:
    headers = {"api-key": API_KEY, "accept": "application/json"}
    workouts, page = [], 1
    print("Fetching workouts", end="", flush=True)
    while True:
        try:
            r = requests.get(
                f"{BASE_URL}/workouts",
                headers=headers,
                params={"page": page, "pageSize": PAGE_SIZE},
                timeout=10,
            )
            if r.status_code == 404:
                break
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"\nError fetching workouts: {e}")
            raise

        batch = r.json().get("workouts", [])
        if not batch:
            break
        done = False
        for w in batch:
            if w.get("id") in known_ids:
                done = True
                break
            workouts.append(w)
        print(".", end="", flush=True)
        if done or len(batch) < PAGE_SIZE:
            break
        page += 1
    print(f" {len(workouts)} new.")
    return workouts


def fetch_templates(template_ids: set) -> dict:
    headers = {"api-key": API_KEY, "accept": "application/json"}
    cache = {}
    ids = [t for t in template_ids if t]
    print(f"Fetching {len(ids)} exercise templates", end="", flush=True)

    def fetch_one(tid):
        try:
            r = requests.get(
                f"{BASE_URL}/exercise_templates/{tid}",
                headers=headers,
                timeout=10,
            )
            if r.status_code == 200:
                t = r.json().get("exercise_template", r.json())
                return tid, {
                    "primary": t.get("primary_muscle_group") or "",
                    "secondary": t.get("secondary_muscle_groups") or [],
                }
        except Exception as e:
            print(f"\nWarning: Failed to fetch template {tid}: {e}")
        return tid, {"primary": "", "secondary": []}

    with ThreadPoolExecutor(max_workers=10) as executor:
        for tid, result in executor.map(fetch_one, ids):
            cache[tid] = result
        print(" done.")
        return cache


def fetch_fresh_data() -> dict:
    conn = get_db()
    known_ids = {
        r[0] for r in conn.execute("SELECT hevy_id FROM workouts").fetchall()
    }
    existing_template_ids = {
        r[0]
        for r in conn.execute("SELECT template_id FROM templates").fetchall()
    }

    new_workouts = fetch_new_workouts(known_ids)

    new_template_ids = {
        ex.get("exercise_template_id", "")
        for w in new_workouts
        for ex in w.get("exercises", [])
    } - existing_template_ids

    new_templates = (
        fetch_templates(new_template_ids) if new_template_ids else {}
    )
    if not new_template_ids:
        print("  No new exercise templates to fetch.")

    if new_workouts:
        insert_workouts(conn, new_workouts)
    if new_templates:
        insert_templates(conn, new_templates)

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("fetched_at", datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    return get_data()


def get_data() -> dict:
    conn = get_db()
    workouts_raw = []
    for r in conn.execute("SELECT raw_data FROM workouts ORDER BY start_time DESC").fetchall():
        try:
            workouts_raw.append(json.loads(r[0]))
        except json.JSONDecodeError:
            print(f"Warning: Failed to decode workout data, skipping")
            continue

    templates_raw = {}
    for r in conn.execute("SELECT template_id, raw_data FROM templates").fetchall():
        try:
            templates_raw[r[0]] = json.loads(r[1])
        except json.JSONDecodeError:
            print(f"Warning: Failed to decode template {r[0]}, skipping")
            continue

    fetched_at = conn.execute(
        "SELECT value FROM meta WHERE key = 'fetched_at'"
    ).fetchone()
    conn.close()

    return {
        "workouts": workouts_raw,
        "templates": templates_raw,
        "fetched_at": fetched_at[0] if fetched_at else "",
    }


def build_exercise_data(raw: dict, df: pd.DataFrame, name: str) -> dict | None:

    ex_df = df[df["exercise"] == name]
    if ex_df.empty:
        return None

    templates = raw.get("templates", {})

    # Template info
    tid = ex_df["muscle_raw"].iloc[0]  # already have muscle_raw
    # Get template_id from raw workouts
    template_id = ""
    secondary_raws = []
    for w in raw.get("workouts", []):
        for ex in w.get("exercises", []):
            if ex.get("title") == name:
                template_id = ex.get("exercise_template_id", "")
                tmpl = templates.get(template_id, {})
                secondary_raws = [
                    s.lower().strip() for s in tmpl.get("secondary", [])
                ]
                break
        if template_id:
            break

    # Detect exercise type from raw sets
    ex_type = "weighted"
    for w in raw.get("workouts", []):
        for ex in w.get("exercises", []):
            if ex.get("title") == name:
                for s in ex.get("sets", []):
                    if s.get("duration_seconds"):
                        ex_type = "timed"
                    elif s.get("weight_kg") is None and s.get("reps"):
                        ex_type = "bodyweight"
                break
        if ex_type != "weighted":
            break

    tmpl = templates.get(template_id, {})
    muscle = classify_muscle(name, tmpl)
    muscle_raw = tmpl.get("primary", "").lower().strip() or classify_muscle_raw(
        name, tmpl
    )

    # e1RM over time (weighted only)
    e1rm_data = {"dates": [], "values": []}
    if ex_type == "weighted":
        e1rm_sub = (
            ex_df[ex_df["e1rm"] > 0].groupby("date")["e1rm"].max().reset_index()
        )
        e1rm_data = {
            "dates": [d.strftime("%Y-%m-%d") for d in e1rm_sub["date"]],
            "values": [round(v, 1) for v in e1rm_sub["e1rm"]],
        }

    # Max reps over time (bodyweight only)
    reps_data = {"dates": [], "values": []}
    if ex_type == "bodyweight":
        reps_grouped = ex_df[ex_df["reps"] > 0].groupby("date")["reps"]
        reps_dates = [d.strftime("%Y-%m-%d") for d in reps_grouped.max().index]
        reps_data = {
            "dates": reps_dates,
            "max_values": [int(v) for v in reps_grouped.max().values],
            "total_values": [int(v) for v in reps_grouped.sum().values],
        }

    # Duration over time (timed only) — pulled from raw workouts
    duration_data = {"dates": [], "max_values": [], "total_values": []}
    if ex_type == "timed":
        dur_by_date = {}
        for w in raw.get("workouts", []):
            w_date = (
                pd.to_datetime(w.get("start_time"), utc=True)
                .tz_localize(None)
                .strftime("%Y-%m-%d")
            )
            for ex in w.get("exercises", []):
                if ex.get("title") != name:
                    continue
                durations = [
                    s.get("duration_seconds") or 0
                    for s in ex.get("sets", [])
                    if s.get("type", "normal") == "normal"
                ]
                if durations:
                    if w_date not in dur_by_date:
                        dur_by_date[w_date] = []
                    dur_by_date[w_date].extend(durations)
        sorted_dates = sorted(dur_by_date.keys())
        duration_data = {
            "dates": sorted_dates,
            "max_values": [max(dur_by_date[d]) for d in sorted_dates],
            "total_values": [sum(dur_by_date[d]) for d in sorted_dates],
        }

    ex_df = ex_df.copy()
    ex_df["week"] = (
        ex_df["date"].dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
    )
    vol_sub = ex_df[~ex_df["is_secondary"]].groupby("week")["volume"].sum()
    vol_data = {
        "weeks": list(vol_sub.index),
        "values": [round(v, 1) for v in vol_sub.values],
    }

    # PRs
    primary = ex_df[~ex_df["is_secondary"]]
    pr = {}
    if not primary.empty and primary["weight_kg"].max() > 0:
        row_wt = primary.loc[primary["weight_kg"].idxmax()]
        row_e1rm = primary.loc[primary["e1rm"].idxmax()]
        row_vol = primary.loc[primary["volume"].idxmax()]
        pr = {
            "by_weight": {
                "weight": round(row_wt["weight_kg"], 1),
                "reps": int(
                    row_wt["reps"]
                ),  # pyright: ignore[reportArgumentType]
                "e1rm": round(row_wt["e1rm"], 1),
                "date": row_wt["date"].strftime("%d %b %Y"),
                "date_iso": row_wt["date"].strftime("%Y-%m-%d"),
            },
            "by_e1rm": {
                "weight": round(row_e1rm["weight_kg"], 1),
                "reps": int(
                    row_e1rm["reps"]
                ),  # pyright: ignore[reportArgumentType]
                "e1rm": round(row_e1rm["e1rm"], 1),
                "date": row_e1rm["date"].strftime("%d %b %Y"),
                "date_iso": row_e1rm["date"].strftime("%Y-%m-%d"),
            },
            "by_vol": {
                "weight": round(row_vol["weight_kg"], 1),
                "reps": int(
                    row_vol["reps"]
                ),  # pyright: ignore[reportArgumentType]
                "e1rm": round(row_vol["e1rm"], 1),
                "date": row_vol["date"].strftime("%d %b %Y"),
                "date_iso": row_vol["date"].strftime("%Y-%m-%d"),
            },
        }

    # Prediction
    prediction = predict_next(df, name)

    # Session history — one entry per date
    sessions = []
    for date, grp in ex_df[~ex_df["is_secondary"]].groupby("date"):
        sets = raw_sets = []
        # get actual sets from raw workouts
        for w in raw.get("workouts", []):
            w_date = pd.to_datetime(w.get("start_time"), utc=True).tz_localize(
                None
            )
            if w_date.date() != date.date():
                continue
            for ex in w.get("exercises", []):
                if ex.get("title") == name:
                    sets = [
                        {
                            "weight_kg": s.get("weight_kg") or 0,
                            "reps": s.get("reps") or 0,
                            "duration_sec": s.get("duration_seconds") or 0,
                        }
                        for s in ex.get("sets", [])
                        if s.get("type", "normal") == "normal"
                        and (
                            (s.get("reps") or 0) > 0
                            or (s.get("duration_seconds") or 0) > 0
                        )
                    ]

                    break
            if sets:
                break

        sessions.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "date_fmt": date.strftime("%d %b %Y"),
                "volume": round(grp["volume"].sum(), 1),
                "top_weight": round(grp["weight_kg"].max(), 1),
                "top_e1rm": round(grp["e1rm"].max(), 1),
                "sets": sets,
            }
        )

    sessions.sort(key=lambda x: x["date"], reverse=True)

    return {
        "name": name,
        "muscle": muscle,
        "muscle_raw": muscle_raw,
        "secondary_raws": secondary_raws,
        "template_id": template_id,
        "exercise_type": ex_type,
        "e1rm": e1rm_data,
        "reps_data": reps_data,
        "duration_data": duration_data,
        "volume": vol_data,
        "pr": pr,
        "prediction": prediction,
        "sessions": sessions,
        "secondary_weights": {
            f"{t}|{m}": w for (t, m), w in SECONDARY_WEIGHTS.items()
        },
    }


def build_pr_index(workouts: list) -> dict:
    pr_weight, pr_e1rm, pr_vol = {}, {}, {}
    for w in sorted(workouts, key=lambda x: x.get("start_time", "")):
        w_date_str = w.get("start_time", "")[:10]
        for ex in w.get("exercises", []):
            name = ex.get("title", "Unknown")
            for s in ex.get("sets", []):
                if s.get("set_type", "normal") != "normal":
                    continue
                weight = s.get("weight_kg") or 0.0
                reps = s.get("reps") or 0
                e1rm = epley(weight, reps)
                vol = weight * reps
                if weight > pr_weight.get(name, (0, ""))[0]:
                    pr_weight[name] = (weight, w_date_str)
                if e1rm > pr_e1rm.get(name, (0, ""))[0]:
                    pr_e1rm[name] = (e1rm, w_date_str)
                if vol > pr_vol.get(name, (0, ""))[0]:
                    pr_vol[name] = (vol, w_date_str)
    return {"weight": pr_weight, "e1rm": pr_e1rm, "vol": pr_vol}


# ── Muscle classification ──────────────────────────────────────────────────────


def classify_muscle(name: str, template: dict) -> str:
    raw = template.get("primary", "")
    if raw:
        m = MUSCLE_NORMALISE.get(raw.lower().strip())
        if m:
            return m
    lower = name.lower()
    for kw, grp in sorted(
        MUSCLE_MAP_FALLBACK.items(), key=lambda x: -len(x[0])
    ):
        if kw in lower:
            return grp
    return "Other"


def classify_muscle_raw(name: str, template: dict) -> str:
    """Return the raw Hevy primary_muscle_group key, or fallback keyword match."""
    raw = template.get("primary", "")
    if raw:
        return raw.lower().strip()
    # Fallback to first matching keyword
    lower = name.lower()
    for kw in sorted(MUSCLE_MAP_FALLBACK.keys(), key=lambda x: -len(x)):
        if kw in lower:
            return kw
    return "other"


# ── Data processing ────────────────────────────────────────────────────────────


def epley(weight: float, reps: int) -> float:
    if weight <= 0 or reps == 0:
        return 0.0
    return weight if reps == 1 else weight * (1 + reps / 30)


def round_to_half(v: float) -> float:
    return round(v * 2) / 2


def build_dataframe(raw: dict) -> pd.DataFrame:
    templates = raw.get("templates", {})
    rows = []
    for w in raw.get("workouts", []):
        date = pd.to_datetime(w.get("start_time"), utc=True).tz_localize(None)
        for ex in w.get("exercises", []):
            name = ex.get("title", "Unknown")
            tid = ex.get("exercise_template_id", "")
            tmpl = templates.get(tid, {})
            muscle = classify_muscle(name, tmpl)
            muscle_raw = tmpl.get("primary", "") or classify_muscle_raw(
                name, tmpl
            )

            secondary_raws = tmpl.get("secondary", [])

            for s in ex.get("sets", []):
                weight = s.get("weight_kg") or 0.0
                reps = s.get("reps") or 0
                duration = s.get("duration_seconds") or 0

                if reps == 0 and duration == 0:
                    continue
                vol = weight * reps if reps > 0 else 0.0
                e1rm = epley(weight, reps) if weight > 0 and reps > 0 else 0.0

                # Primary muscle — full volume
                rows.append(
                    {
                        "date": date,
                        "exercise": name,
                        "muscle": muscle,
                        "muscle_raw": muscle_raw,
                        "weight_kg": weight,
                        "reps": reps,
                        "volume": vol,
                        "e1rm": e1rm,
                        "duration_sec": duration,
                        "set_type": s.get("set_type", "normal"),
                        "is_secondary": False,
                    }
                )

                # For upper_back exercises, also count traps and rhomboids at full volume
                # since Hevy uses upper_back as a catch-all for the entire upper back complex
                if muscle_raw == "upper_back":
                    for also in ["traps", "rhomboids"]:
                        also_normalised = MUSCLE_NORMALISE.get(also, "")
                        if also_normalised:
                            rows.append(
                                {
                                    "date": date,
                                    "exercise": name,
                                    "muscle": also_normalised,
                                    "muscle_raw": also,
                                    "weight_kg": weight,
                                    "reps": reps,
                                    "volume": vol,
                                    "e1rm": 0.0,
                                    "duration_sec": 0.0,
                                    "set_type": s.get("set_type", "normal"),
                                    "is_secondary": False,
                                }
                            )

                # Secondary muscles — 50% volume, no e1rm tracking
                for sec_raw in secondary_raws:
                    sec_raw_clean = sec_raw.lower().strip()
                    sec_normalised = MUSCLE_NORMALISE.get(sec_raw_clean, "")
                    if not sec_normalised:
                        continue
                    sec_fraction = SECONDARY_WEIGHTS.get(
                        (tid, sec_raw_clean), 0.5
                    )
                    rows.append(
                        {
                            "date": date,
                            "exercise": name,
                            "muscle": sec_normalised,
                            "muscle_raw": sec_raw_clean,
                            "weight_kg": weight,
                            "reps": reps,
                            "volume": round(vol * sec_fraction, 1),
                            "e1rm": 0.0,
                            "duration_sec": 0.0,
                            "set_type": s.get("set_type", "normal"),
                            "is_secondary": True,
                        }
                    )

                    # When upper_back appears as secondary, also credit traps and rhomboids at same 50% weight
                    if sec_raw_clean == "upper_back":
                        for also in ["traps", "rhomboids"]:
                            also_normalised = MUSCLE_NORMALISE.get(also, "")
                            if also_normalised:
                                rows.append(
                                    {
                                        "date": date,
                                        "exercise": name,
                                        "muscle": also_normalised,
                                        "muscle_raw": also,
                                        "weight_kg": weight,
                                        "reps": reps,
                                        "volume": round(vol * sec_fraction, 1),
                                        "e1rm": 0.0,
                                        "duration_sec": 0.0,
                                        "set_type": s.get("set_type", "normal"),
                                        "is_secondary": True,
                                    }
                                )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["set_type"] == "normal"].copy()
    df.sort_values("date", inplace=True)
    return df


# ── Predictions ────────────────────────────────────────────────────────────────


def calc_acwr(df: pd.DataFrame, exercise: str, ref_date: pd.Timestamp) -> float:
    """
    Acute:Chronic Workload Ratio.
    Acute   = total volume in last 7 days
    Chronic = avg weekly volume over last 6 weeks (42 days)
              but only counting weeks that actually had training,
              with a minimum of 2 active weeks to avoid false positives
              after returning from a break.
    """
    ex = df[(df["exercise"] == exercise) & (~df["is_secondary"])].copy()
    if ex.empty:
        return 0.0

    acute_start = ref_date - pd.Timedelta(days=7)
    chronic_start = ref_date - pd.Timedelta(days=42)

    acute_vol = ex[ex["date"] > acute_start]["volume"].sum()

    # Compute weekly volumes over the chronic window
    chronic_ex = ex[
        (ex["date"] > chronic_start) & (ex["date"] <= ref_date)
    ].copy()
    if chronic_ex.empty:
        return 0.0

    chronic_ex["week"] = chronic_ex["date"].dt.to_period("W")
    weekly_vols = chronic_ex.groupby("week")["volume"].sum()

    # Only count weeks with actual training
    active_weeks = weekly_vols[weekly_vols > 0]

    # Need at least 2 active weeks in the chronic window to compute a meaningful ratio
    # This prevents false positives when returning from a break
    if len(active_weeks) < 2:
        return 0.0

    chronic_weekly_avg = active_weeks.mean()

    if chronic_weekly_avg == 0:
        return 0.0

    return round(acute_vol / chronic_weekly_avg, 2)


def predict_next(df: pd.DataFrame, exercise: str) -> dict:
    ex = df[df["exercise"] == exercise].copy()
    if ex.empty:
        return {}

    best_e1rm = ex["e1rm"].max()
    last_date = ex["date"].max()
    last_sess = ex[ex["date"] == last_date]
    is_bw = last_sess["weight_kg"].max() == 0
    days_since = max((pd.Timestamp.now() - last_date).days, 0)

    top_weight = 0 if is_bw else last_sess["weight_kg"].max()
    top_reps = (
        int(last_sess["reps"].max())
        if is_bw
        else int(last_sess.loc[last_sess["weight_kg"].idxmax(), "reps"])
    )

    if days_since > STALE_DAYS:
        return {
            "exercise": exercise,
            "last_weight": 0 if is_bw else round_to_half(top_weight),
            "last_reps": top_reps,
            "best_e1rm": round_to_half(best_e1rm),
            "rec_weight": 0 if is_bw else round_to_half(top_weight),
            "rec_reps": top_reps,
            "deload": False,
            "days_since": int(days_since),
            "is_bw": bool(is_bw),
            "status": "returning",
            "note": f"Returning after {days_since}d — resume last load",
        }

    ex["week"] = ex["date"].dt.to_period("W")
    weekly_vol = ex.groupby("week")["volume"].sum().sort_index()
    acwr = calc_acwr(df, exercise, last_date)
    deload = acwr > 1.3 and days_since <= STALE_DAYS

    # Always compute normal progression
    if is_bw:
        rec_weight, rec_reps = 0, top_reps + 1
        note = f"Bodyweight — target {top_reps + 1} reps"
        status = "progress"
    elif top_reps >= UPPER_REP_TARGET:
        rec_weight = round_to_half(top_weight + WEIGHT_INCREMENT)
        rec_reps = REP_RESET_AFTER_BUMP
        note = f"Hit {top_reps} reps — go up to {rec_weight} kg"
        status = "bump"
    else:
        rec_weight = round_to_half(top_weight)
        rec_reps = top_reps + 1
        note = f"Same weight — target {top_reps + 1} reps"
        status = "progress"

    # Deload info as separate fields — frontend decides whether to show
    deload_rec_weight = round_to_half(top_weight * 0.9) if not is_bw else 0
    deload_rec_reps = max(1, int(top_reps * 0.7))
    deload_note = (
        f"ACWR {acwr:.2f} — reduce load, risk of overreaching"
        if acwr > DELOAD_THRESHOLD
        else f"ACWR {acwr:.2f}"
    )

    return {
        "exercise": exercise,
        "last_weight": 0 if is_bw else round_to_half(top_weight),
        "last_reps": int(top_reps),
        "best_e1rm": round_to_half(float(best_e1rm)),
        "rec_weight": float(rec_weight),
        "rec_reps": int(rec_reps),
        "rec_weight": float(rec_weight),
        "rec_reps": int(rec_reps),
        "status": status,
        "note": note,
        "deload": bool(deload),
        "acwr": float(acwr),
        "deload_rec_weight": float(deload_rec_weight),
        "deload_rec_reps": int(deload_rec_reps),
        "deload_note": deload_note,
        "days_since": int(days_since),
        "is_bw": bool(is_bw),
        "status": status,
        "note": note,
    }


def rank_exercises(df: pd.DataFrame) -> list[str]:
    now = pd.Timestamp.now()
    scores = {}
    for name, grp in df.groupby("exercise"):
        sessions = grp["date"].drop_duplicates()
        scores[name] = sum(1.0 / max((now - d).days, 1) for d in sessions)
    return sorted(scores, key=scores.get, reverse=True)


# ── API payload builder ────────────────────────────────────────────────────────


def build_api_payload(raw: dict) -> dict:
    df = build_dataframe(raw)
    if df.empty:
        return {"error": "No set data found"}

    all_exercises = df["exercise"].unique()
    exercises_detail = {}
    for name in all_exercises:
        result = build_exercise_data(raw, df, name)
        if result:
            exercises_detail[name] = result

    ranked = rank_exercises(df)
    top_exs = ranked[:TOP_N]
    preds = [p for ex in ranked if (p := predict_next(df, ex))]

    # Volume over time — all exercises
    df["week"] = (
        df["date"].dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
    )
    vol_data = {}
    for ex in ranked:
        sub = df[df["exercise"] == ex].groupby("week")["volume"].sum()
        vol_data[ex] = {
            "weeks": list(sub.index),
            "values": [round(v, 1) for v in sub.values],
        }

    # e1RM over time — all exercises
    e1rm_data = {}
    for ex in ranked:
        sub = df[(df["exercise"] == ex) & (df["e1rm"] > 0)]
        sub = sub.groupby("date")["e1rm"].max().reset_index()
        e1rm_data[ex] = {
            "dates": [d.strftime("%Y-%m-%d") for d in sub["date"]],
            "values": [round(v, 1) for v in sub["e1rm"]],
        }

    # e1RM progress — current vs 30 days ago
    now = pd.Timestamp.now()
    thirty_days_ago = now - pd.Timedelta(days=30)
    progress_e1rm = {}
    for ex in ranked:
        sub = df[
            (df["exercise"] == ex) & (df["e1rm"] > 0) & (~df["is_secondary"])
        ]
        if sub.empty:
            continue
        current_e1rm = (
            sub[sub["date"] >= thirty_days_ago]["e1rm"].max()
            if not sub[sub["date"] >= thirty_days_ago].empty
            else None
        )
        past_e1rm = (
            sub[sub["date"] < thirty_days_ago]["e1rm"].max()
            if not sub[sub["date"] < thirty_days_ago].empty
            else None
        )
        if current_e1rm and past_e1rm:
            change_pct = round((current_e1rm - past_e1rm) / past_e1rm * 100, 1)
        else:
            change_pct = None
        progress_e1rm[ex] = {
            "current": round(float(current_e1rm), 1) if current_e1rm else None,
            "past": round(float(past_e1rm), 1) if past_e1rm else None,
            "change": change_pct,
        }

    # Volume progress — current 30d vs previous 30d
    progress_vol = {}
    for ex in ranked:
        sub = df[(df["exercise"] == ex) & (~df["is_secondary"])].copy()
        if sub.empty:
            continue
        current_vol = sub[sub["date"] >= thirty_days_ago]["volume"].sum()
        past_vol = sub[
            (sub["date"] >= thirty_days_ago - pd.Timedelta(days=30))
            & (sub["date"] < thirty_days_ago)
        ]["volume"].sum()
        if current_vol > 0 and past_vol > 0:
            change_pct = round((current_vol - past_vol) / past_vol * 100, 1)
        else:
            change_pct = None
        progress_vol[ex] = {
            "current": round(float(current_vol), 1),
            "past": round(float(past_vol), 1),
            "change": change_pct,
        }

    # Muscle breakdown — send as daily series so frontend can filter by window
    muscle_daily = df.drop_duplicates(["date", "muscle"]).assign(
        date_str=df["date"].dt.strftime("%Y-%m-%d")
    )
    # Per-date volume per muscle
    muscle_vol_daily = (
        df.groupby([df["date"].dt.strftime("%Y-%m-%d"), "muscle"])["volume"]
        .sum()
        .reset_index()
    )
    muscle_vol_daily.columns = ["date", "muscle", "volume"]

    # All unique muscles, stable order by all-time volume
    all_muscles = (
        df.groupby("muscle")["volume"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )

    # Build per-muscle date→volume and date→session_count series
    # Muscle breakdown — send as daily time series using raw muscle keys
    muscle_daily_raw = df.drop_duplicates(["date", "muscle_raw"]).assign(
        date_str=df["date"].dt.strftime("%Y-%m-%d")
    )
    muscle_vol_daily_raw = (
        df.groupby([df["date"].dt.strftime("%Y-%m-%d"), "muscle_raw"])["volume"]
        .sum()
        .reset_index()
    )
    muscle_vol_daily_raw.columns = ["date", "muscle", "volume"]

    all_muscles_raw = (
        df.groupby("muscle_raw")["volume"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )

    muscle_series = {}
    for m in all_muscles_raw:
        vol_sub = muscle_vol_daily_raw[muscle_vol_daily_raw["muscle"] == m]

        # Primary sessions — full count
        primary_dates = (
            df[(df["muscle_raw"] == m) & (~df["is_secondary"])]["date"]
            .dt.strftime("%Y-%m-%d")
            .drop_duplicates()
            .tolist()
        )
        # Secondary sessions — only dates not already covered by primary
        secondary_dates = (
            df[(df["muscle_raw"] == m) & (df["is_secondary"])]["date"]
            .dt.strftime("%Y-%m-%d")
            .drop_duplicates()
        )
        secondary_only = [
            d for d in secondary_dates if d not in set(primary_dates)
        ]

        # Combine: primary dates + secondary-only dates each weighted 0.5
        # We encode this as a list of (date, weight) but since the frontend
        # just counts dates, we duplicate primary and send secondary separately
        freq_dates = (
            primary_dates + secondary_only
        )  # secondary_only counted at 0.5 in frontend

        muscle_series[m] = {
            "vol_dates": list(vol_sub["date"]),
            "vol_values": [round(v, 1) for v in vol_sub["volume"]],
            "freq_dates": freq_dates,
            "freq_dates_secondary": secondary_only,  # frontend uses this to apply 0.5 weight
        }

    # Calendar heatmap data — per day: set count, volume, muscles hit
    df_primary = df[~df["is_secondary"]].copy()
    cal_days = (
        df_primary.groupby(df_primary["date"].dt.strftime("%Y-%m-%d"))
        .agg(
            sets=("reps", "count"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )
    cal_days.columns = ["date", "sets", "volume"]

    # Muscles hit per day (primary only, normalised display names)
    muscles_per_day = (
        df_primary.drop_duplicates(["date", "muscle"])
        .groupby(df_primary["date"].dt.strftime("%Y-%m-%d"))["muscle"]
        .apply(list)
        .reset_index()
    )
    muscles_per_day.columns = ["date", "muscles"]
    cal_merged = cal_days.merge(muscles_per_day, on="date", how="left")

    calendar = {
        row["date"]: {
            "sets": int(row["sets"]),
            "volume": round(row["volume"], 1),
            "muscles": (
                row["muscles"] if isinstance(row["muscles"], list) else []
            ),
        }
        for _, row in cal_merged.iterrows()
    }

    # PRs for top exercises — send both max-weight and max-e1rm sets
    prs = []
    for ex in top_exs:
        sub = df[df["exercise"] == ex]
        if sub.empty or sub["weight_kg"].max() == 0:
            continue

        row_wt = sub.loc[sub["weight_kg"].idxmax()]
        row_e1rm = sub.loc[sub["e1rm"].idxmax()]
        row_vol = sub.loc[sub["volume"].idxmax()]

        prs.append(
            {
                "exercise": ex,
                "by_weight": {
                    "weight": round(row_wt["weight_kg"], 1),
                    "reps": int(row_wt["reps"]),
                    "e1rm": round(row_wt["e1rm"], 1),
                    "volume": round(row_wt["volume"], 1),
                    "date": row_wt["date"].strftime("%d %b %Y"),
                    "date_iso": row_wt["date"].strftime("%Y-%m-%d"),
                },
                "by_e1rm": {
                    "weight": round(row_e1rm["weight_kg"], 1),
                    "reps": int(row_e1rm["reps"]),
                    "e1rm": round(row_e1rm["e1rm"], 1),
                    "volume": round(row_e1rm["volume"], 1),
                    "date": row_e1rm["date"].strftime("%d %b %Y"),
                    "date_iso": row_e1rm["date"].strftime("%Y-%m-%d"),
                },
                "by_vol": {
                    "weight": round(row_vol["weight_kg"], 1),
                    "reps": int(row_vol["reps"]),
                    "e1rm": round(row_vol["e1rm"], 1),
                    "volume": round(row_vol["volume"], 1),
                    "date": row_vol["date"].strftime("%d %b %Y"),
                    "date_iso": row_vol["date"].strftime("%Y-%m-%d"),
                },
            }
        )

    total_vol_t = round(df["volume"].sum() / 1000, 1)

    # Best time/day to train
    df_primary = df[~df["is_secondary"]].copy()
    df_primary["hour"] = pd.to_datetime(df_primary["date"]).dt.hour
    df_primary["day_of_week"] = pd.to_datetime(
        df_primary["date"]
    ).dt.dayofweek  # 0=Mon

    # Per-session stats — one row per unique date
    sessions = (
        df_primary.groupby("date")
        .agg(sets=("reps", "count"), volume=("volume", "sum"))
        .reset_index()
    )
    sessions["hour"] = sessions["date"].dt.hour
    sessions["day_of_week"] = sessions["date"].dt.dayofweek
    sessions["date_str"] = sessions["date"].dt.strftime("%Y-%m-%d")

    timing_data = [
        {
            "date": row["date_str"],
            "day": int(row["day_of_week"]),
            "hour": int(row["hour"]),
            "sets": int(row["sets"]),
            "volume": round(row["volume"], 1),
        }
        for _, row in sessions.iterrows()
    ]

    def get_week(d):
        return d - timedelta(days=d.weekday())  # Monday of that week

    workout_dates = {
        pd.to_datetime(w["start_time"], utc=True).tz_localize(None).date()
        for w in raw.get("workouts", [])
        if w.get("start_time")
    }
    trained_weeks = {get_week(d) for d in workout_dates}

    streak = 0
    current_week = get_week(date.today())
    while current_week in trained_weeks or current_week == get_week(
        date.today()
    ):
        if current_week in trained_weeks:
            streak += 1
        elif streak > 0:
            break
        current_week -= timedelta(weeks=1)

    return {
        "summary": {
            "workouts": int(df["date"].dt.date.nunique()),
            "volume_t": total_vol_t,
            "exercises": int(df["exercise"].nunique()),
            "date_range": f"{df['date'].min().strftime('%b %Y')} – {df['date'].max().strftime('%b %Y')}",
            "fetched_at": raw.get("fetched_at", ""),
            "streak": streak,
        },
        "secondary_weights": {
            f"{tid}|{muscle}": weight
            for (tid, muscle), weight in SECONDARY_WEIGHTS.items()
        },
        "exercises": top_exs,
        "volume": vol_data,
        "e1rm": e1rm_data,
        "muscle_series": muscle_series,
        "muscles": all_muscles_raw,
        "prs": prs,
        "predictions": preds,
        "calendar": calendar,
        "timing": timing_data,
        "progress_e1rm": progress_e1rm,
        "progress_vol": progress_vol,
        "exercises_detail": exercises_detail,
        "pr_index": build_pr_index(raw.get("workouts", [])),
    }


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    try:
        conn = get_db()
        payload = load_payload(conn)
        if payload is None:
            payload = build_api_payload(get_data())
            save_payload(conn, payload)
            conn.commit()
        conn.close()
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    try:
        raw = fetch_fresh_data()
        payload = build_api_payload(raw)
        conn = get_db()
        save_payload(conn, payload)
        conn.commit()
        conn.close()
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cache-info")
def cache_info():
    conn = get_db()
    fetched_at = conn.execute(
        "SELECT value FROM meta WHERE key = 'fetched_at'"
    ).fetchone()
    n_workouts = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    conn.close()

    if not fetched_at:
        return jsonify({"exists": False})

    fetched_dt = datetime.fromisoformat(fetched_at[0])
    age_h = round((datetime.now() - fetched_dt).total_seconds() / 3600, 1)
    return jsonify(
        {
            "exists": True,
            "age_hours": age_h,
            "fetched_at": fetched_at[0],
            "workouts": n_workouts,
        }
    )


@app.route("/workout/<date>")
def workout_detail(date):
    """Serve the workout detail page — the JS fetches /api/workout/<date>."""
    return render_template("workout.html", date=date)


@app.route("/export/next-session.json")
def export_next_session_file():
    raw = get_data()
    payload = build_api_payload(raw)

    export = {
        "generated_at": datetime.now().isoformat(),
        "summary": payload["summary"],
        "next_session": payload["predictions"],
        "personal_records": payload["prs"],
        "progress_e1rm": payload["progress_e1rm"],
        "progress_vol": payload["progress_vol"],
    }

    response = app.response_class(
        response=json.dumps(export, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": "attachment;filename=next-session.json"
        },
    )
    return response


@app.route("/api/workout/<date>")
def api_workout(date):
    try:
        from datetime import date as date_type, timedelta, datetime

        raw = get_data()
        templates = raw.get("templates", {})
        workouts = raw.get("workouts", [])

        # ── Pass 1: build all-time PRs chronologically ─────────────────────────
        conn = get_db()
        payload_cached = load_payload(conn)
        conn.close()
        pr_index = (
            payload_cached.get("pr_index", {})
            if payload_cached
            else build_pr_index(workouts)
        )

        pr_weight = pr_index.get("weight", {})
        pr_e1rm = pr_index.get("e1rm", {})
        pr_vol = pr_index.get("vol", {})

        # ── Pass 2: find workouts in the requested window ──────────────────────
        target = date_type.fromisoformat(date)
        search_week = request.args.get("range") == "week"
        if search_week:
            week_start = target - timedelta(days=target.weekday())
            week_end = week_start + timedelta(days=6)

            def in_window(d):
                return week_start <= d <= week_end

        else:

            def in_window(d):
                return d == target

        def parse_date(ts):
            if not ts:
                return None
            try:
                return date_type.fromisoformat(ts[:10])
            except:
                return None

        # ── Pass 3: build response, flagging PR sets ───────────────────────────
        day_workouts = []
        for w in workouts:
            w_date = parse_date(w.get("start_time", ""))
            if not w_date or not in_window(w_date):
                continue

            w_date_str = w.get("start_time", "")[:10]

            duration_min = None
            if w.get("start_time") and w.get("end_time"):
                try:
                    s = w["start_time"][:19]
                    e = w["end_time"][:19]
                    duration_min = round(
                        (
                            datetime.fromisoformat(e)
                            - datetime.fromisoformat(s)
                        ).total_seconds()
                        / 60
                    )
                except:
                    pass

            # Track which exercises have already received a PR badge this workout
            awarded_pr_weight = set()
            awarded_pr_e1rm = set()
            awarded_pr_vol = set()

            exercises = []
            total_vol = 0.0
            for ex in w.get("exercises", []):
                name = ex.get("title", "Unknown")
                tid = ex.get("exercise_template_id", "")
                tmpl = templates.get(tid, {})
                muscle = classify_muscle(name, tmpl)
                muscle_raw = tmpl.get(
                    "primary", ""
                ).lower().strip() or classify_muscle_raw(name, tmpl)
                secondary_raws = [
                    s.lower().strip() for s in tmpl.get("secondary", [])
                ]

                sets, ex_vol = [], 0.0

                for s in ex.get("sets", []):
                    weight = s.get("weight_kg") or 0.0
                    reps = s.get("reps") or 0
                    vol = weight * reps
                    ex_vol += vol
                    e1rm = round(epley(weight, reps), 1)

                    is_pr_weight = (
                        weight > 0
                        and name not in awarded_pr_weight
                        and pr_weight.get(name, (0, ""))[1] == w_date_str
                        and weight >= pr_weight.get(name, (0, ""))[0]
                    )
                    is_pr_e1rm = (
                        e1rm > 0
                        and name not in awarded_pr_e1rm
                        and pr_e1rm.get(name, (0, ""))[1] == w_date_str
                        and e1rm >= pr_e1rm.get(name, (0, ""))[0]
                    )
                    is_pr_vol = (
                        vol > 0
                        and name not in awarded_pr_vol
                        and pr_vol.get(name, (0, ""))[1] == w_date_str
                        and vol >= pr_vol.get(name, (0, ""))[0]
                    )

                    if is_pr_weight:
                        awarded_pr_weight.add(name)
                    if is_pr_e1rm:
                        awarded_pr_e1rm.add(name)
                    if is_pr_vol:
                        awarded_pr_vol.add(name)

                    sets.append(
                        {
                            "type": s.get("set_type", "normal"),
                            "weight_kg": round(weight, 2),
                            "reps": reps,
                            "rpe": s.get("rpe"),
                            "e1rm": e1rm,
                            "volume": round(vol, 1),
                            "pr_weight": is_pr_weight,
                            "pr_e1rm": is_pr_e1rm,
                            "pr_vol": is_pr_vol,
                        }
                    )

                total_vol += ex_vol
                exercises.append(
                    {
                        "name": name,
                        "muscle": muscle,
                        "muscle_raw": muscle_raw,
                        "secondary_raws": secondary_raws,
                        "template_id": tid,
                        "notes": ex.get("notes", ""),
                        "sets": sets,
                        "volume": round(ex_vol, 1),
                    }
                )

            day_workouts.append(
                {
                    "id": w.get("id", ""),
                    "title": w.get("title", "Workout"),
                    "start_time": w.get("start_time", ""),
                    "end_time": w.get("end_time", ""),
                    "duration_min": duration_min,
                    "description": w.get("description", ""),
                    "exercises": exercises,
                    "total_volume": round(total_vol, 1),
                }
            )

        if not day_workouts:
            label = f"the week of {date}" if search_week else date
            return jsonify({"error": f"No workout found for {label}"}), 404

        day_workouts.sort(key=lambda x: x["start_time"])
        return jsonify(
            {
                "date": date,
                "workouts": day_workouts,
                "secondary_weights": {
                    f"{tid}|{muscle}": weight
                    for (tid, muscle), weight in SECONDARY_WEIGHTS.items()
                },
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/exercise/<path:name>")
def exercise_detail(name):
    return render_template("exercise.html", name=name)


@app.route("/api/exercise/<path:name>")
def api_exercise(name):
    try:
        conn = get_db()
        payload = load_payload(conn)
        conn.close()
        if payload is None:
            payload = build_api_payload(get_data())
        detail = payload.get("exercises_detail", {}).get(name)
        if not detail:
            return jsonify({"error": f"Exercise '{name}' not found"}), 404
        return jsonify(detail)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(Path(__file__).parent / "static", filename)


@app.route("/month/<month_str>")
def page_month(month_str):
    return render_template("month.html", month=month_str)


@app.route("/api/month/<month_str>")
def api_month(month_str):
    try:
        from datetime import datetime

        raw = get_data()
        templates = raw.get("templates", {})
        workouts = raw.get("workouts", [])

        # Filter to this month
        month_workouts = [
            w for w in workouts if w.get("start_time", "")[:7] == month_str
        ]

        if not month_workouts:
            return jsonify({"error": f"No workouts found for {month_str}"}), 404

        month_workouts.sort(key=lambda x: x["start_time"])

        # Aggregate stats and per-workout summary list
        total_duration = 0
        total_sets = 0
        total_volume = 0.0
        muscle_volume = {}  # muscle_raw -> volume (for heatmap)
        workout_list = []

        for w in month_workouts:
            duration_min = None
            if w.get("start_time") and w.get("end_time"):
                try:
                    s = w["start_time"][:19]
                    e = w["end_time"][:19]
                    duration_min = round(
                        (
                            datetime.fromisoformat(e)
                            - datetime.fromisoformat(s)
                        ).total_seconds()
                        / 60
                    )
                    total_duration += duration_min
                except:
                    pass

            w_vol = 0.0
            w_sets = 0
            muscles_hit = set()

            for ex in w.get("exercises", []):
                name = ex.get("title", "")
                tid = ex.get("exercise_template_id", "")
                tmpl = templates.get(tid, {})
                muscle_raw = tmpl.get(
                    "primary", ""
                ).lower().strip() or classify_muscle_raw(name, tmpl)
                secondary_raws = [
                    s.lower().strip() for s in tmpl.get("secondary", [])
                ]

                ex_vol = sum(
                    (s.get("weight_kg") or 0) * (s.get("reps") or 0)
                    for s in ex.get("sets", [])
                    if s.get("set_type", "normal") == "normal"
                )
                w_vol += ex_vol
                w_sets += len(ex.get("sets", []))

                if muscle_raw and muscle_raw != "other":
                    muscle_volume[muscle_raw] = (
                        muscle_volume.get(muscle_raw, 0) + ex_vol
                    )
                    muscles_hit.add(muscle_raw)

                for sec in secondary_raws:
                    if not sec or sec == "other":
                        continue
                    frac = SECONDARY_WEIGHTS.get((tid, sec), 0.5)
                    muscle_volume[sec] = (
                        muscle_volume.get(sec, 0) + ex_vol * frac
                    )

            total_volume += w_vol
            total_sets += w_sets

            workout_list.append(
                {
                    "date": w["start_time"][:10],
                    "title": w.get("title", "Workout"),
                    "duration_min": duration_min,
                    "volume": round(w_vol, 1),
                    "muscles": classify_muscle(
                        (
                            w["exercises"][0].get("title", "")
                            if w.get("exercises")
                            else ""
                        ),
                        templates.get(
                            (
                                w["exercises"][0].get(
                                    "exercise_template_id", ""
                                )
                                if w.get("exercises")
                                else ""
                            ),
                            {},
                        ),
                    ),
                }
            )

        return jsonify(
            {
                "month": month_str,
                "summary": {
                    "workouts": len(month_workouts),
                    "duration_min": total_duration,
                    "sets": total_sets,
                    "volume": round(total_volume, 1),
                },
                "workout_list": workout_list,
                "muscle_volume": muscle_volume,
                "secondary_weights": {
                    f"{tid}|{muscle}": weight
                    for (tid, muscle), weight in SECONDARY_WEIGHTS.items()
                },
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    if not API_KEY:
        sys.exit("No HEVY_API_KEY found. Add it to .env or export it.")

    conn = get_db()
    workout_count = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    conn.close()

    if workout_count == 0:
        print("⚡  Fetching your workout history from Hevy...")
        fetch_fresh_data()

    print(f"⚡  Hevy Dashboard → http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(debug=FLASK_DEBUG, host=FLASK_HOST, port=FLASK_PORT)
