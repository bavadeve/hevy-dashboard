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
from datetime import datetime
from pathlib import Path

import requests
import numpy as np
import pandas as pd
import flask
from flask import Flask, jsonify, render_template, request, send_from_directory
from dotenv import load_dotenv


class NumpyEncoder(json.JSONEncoder):
    """Converts numpy scalar types to native Python so Flask can serialise them."""
    def default(self, obj):
        if isinstance(obj, np.integer):  return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.bool_):    return bool(obj)
        if isinstance(obj, np.ndarray):  return obj.tolist()
        return super().default(obj)

class NumpyJSONProvider(flask.json.provider.DefaultJSONProvider):
    """Flask 2.2+ JSON provider that handles numpy types."""
    def dumps(self, obj, **kwargs):
        kwargs.setdefault("cls", NumpyEncoder)
        return super().dumps(obj, **kwargs)

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY             = os.environ.get("HEVY_API_KEY", "").strip()
BASE_URL            = "https://api.hevyapp.com/v1"
PAGE_SIZE           = 10
TOP_N               = 8
CACHE_FILE          = Path(__file__).parent / "cache.json"
CACHE_MAX_AGE_HOURS = 24

STALE_DAYS           = 21
DELOAD_THRESHOLD     = 0.90
UPPER_REP_TARGET     = 12
WEIGHT_INCREMENT     = 2.0
REP_RESET_AFTER_BUMP = 8

MUSCLE_MAP_FALLBACK = {
    "bench": "Chest", "chest fly": "Chest", "pec": "Chest",
    "squat": "Legs", "lunge": "Legs", "leg press": "Legs",
    "leg curl": "Legs", "leg extension": "Legs", "hack squat": "Legs",
    "deadlift": "Back", "barbell row": "Back", "dumbbell row": "Back",
    "lat pulldown": "Back", "pull-up": "Back", "pullup": "Back",
    "chin-up": "Back", "chinup": "Back", "seated row": "Back", "rdl": "Back",
    "shoulder press": "Shoulders", "overhead press": "Shoulders",
    "military press": "Shoulders", "arnold press": "Shoulders",
    "lateral raise": "Shoulders", "front raise": "Shoulders",
    "face pull": "Shoulders", "rear delt": "Shoulders",
    "curl": "Biceps", "bicep": "Biceps", "hammer curl": "Biceps",
    "tricep": "Triceps", "triceps": "Triceps",
    "pushdown": "Triceps", "skull": "Triceps",
    "calf": "Calves", "calves": "Calves",
    "plank": "abdominals", "crunch": "abdominals", "ab ": "abdominals", "sit-up": "abdominals",
}

MUSCLE_NORMALISE = {
    "chest": "Chest", "upper_chest": "Chest", "lower_chest": "Chest",
    "quadriceps": "Legs", "hamstrings": "Legs", "glutes": "Legs",
    "adductors": "Legs", "abductors": "Legs", "hip_flexors": "Legs",
    "calves": "Calves",
    "lats":       "Back",
    "upper_back": "Traps",    # upper_back = traps + rhomboids catch-all
    "lower_back": "Back",
    "traps":      "Traps",
    "rhomboids":  "Traps",
    "shoulders": "Shoulders", "front_delts": "Shoulders",
    "side_delts": "Shoulders", "rear_delts": "Shoulders",
    "biceps": "Biceps", "triceps": "Triceps", "forearms": "Forearms",
    "abs": "abdominals", "abdominals": "abdominals", "obliques": "abdominals", "core": "abdominals", "neck": "Neck",
}
# Per-exercise secondary muscle weights — (template_id, muscle_raw) → fraction of primary volume
# Default is 0.5 for any secondary not listed here
SECONDARY_WEIGHTS = {

    # ── Romanian Deadlift ────────────────────────────────────────────────────
    # Glutes and lower back are heavily loaded throughout the lift
    ("72CFFAD5", "glutes"):     0.75,
    ("72CFFAD5", "lower_back"): 0.60,
    ("72CFFAD5", "upper_back"): 0.30,
    ("72CFFAD5", "lats"):       0.20,

    # ── Single Leg RDL ───────────────────────────────────────────────────────
    ("937292AB", "glutes"):     0.75,
    ("937292AB", "lower_back"): 0.50,

    # ── Dumbbell Deadlift ────────────────────────────────────────────────────
    # Full posterior chain — glutes and quads genuinely close to primary
    ("5F4E6DD3", "hamstrings"):  0.80,
    ("5F4E6DD3", "quadriceps"):  0.60,
    ("5F4E6DD3", "lower_back"):  0.60,
    ("5F4E6DD3", "upper_back"):  0.35,
    ("5F4E6DD3", "lats"):        0.25,
    ("5F4E6DD3", "traps"):       0.25,

    # ── Bulgarian Split Squat ────────────────────────────────────────────────
    # Glutes genuinely close to primary, hamstrings less so
    ("B5D3A742", "glutes"):     0.70,
    ("B5D3A742", "hamstrings"): 0.40,

    # ── Dumbbell Step Up ─────────────────────────────────────────────────────
    ("BF6ECE89", "glutes"):     0.65,
    ("BF6ECE89", "hamstrings"): 0.35,

    # ── Squat (Dumbbell) ─────────────────────────────────────────────────────
    ("DCFF3E9F", "hamstrings"): 0.45,
    ("DCFF3E9F", "glutes"):     0.60,

    # ── Split Squat ──────────────────────────────────────────────────────────
    ("20C1A3CB", "hamstrings"): 0.40,
    ("20C1A3CB", "glutes"):     0.60,

    # ── Dumbbell Row ─────────────────────────────────────────────────────────
    # Upper back genuinely close to primary, biceps moderate, forearms minimal
    ("F1E57334", "upper_back"): 0.70,
    ("F1E57334", "biceps"):     0.40,
    ("F1E57334", "forearms"):   0.20,

    # ── Bent Over Row ────────────────────────────────────────────────────────
    ("23E92538", "lats"):       0.65,
    ("23E92538", "biceps"):     0.40,
    ("23E92538", "forearms"):   0.20,

    # ── Meadows Row ──────────────────────────────────────────────────────────
    ("C732C341", "lats"):       0.65,
    ("C732C341", "biceps"):     0.40,
    ("C732C341", "forearms"):   0.20,

    # ── Pullover ─────────────────────────────────────────────────────────────
    # Chest genuinely involved, upper_back moderate, triceps minimal
    ("67280085", "chest"):      0.55,
    ("67280085", "upper_back"): 0.40,
    ("67280085", "triceps"):    0.20,

    # ── Incline Bench Press ──────────────────────────────────────────────────
    # Triceps close to primary, shoulders moderate
    ("07B38369", "triceps"):    0.55,
    ("07B38369", "shoulders"):  0.35,

    # ── Bench Press (Dumbbell) ───────────────────────────────────────────────
    ("3601968B", "triceps"):    0.55,
    ("3601968B", "shoulders"):  0.30,

    # ── Floor Press ──────────────────────────────────────────────────────────
    ("756EE329", "triceps"):    0.60,  # triceps extra loaded at lockout
    ("756EE329", "shoulders"):  0.25,

    # ── Push Up ──────────────────────────────────────────────────────────────
    ("392887AA", "triceps"):    0.55,
    ("392887AA", "shoulders"):  0.30,

    # ── Overhead / Shoulder Press ────────────────────────────────────────────
    ("6AC96645", "triceps"):    0.50,
    ("878CD1D0", "triceps"):    0.50,

    # ── Arnold Press ─────────────────────────────────────────────────────────
    ("A69FF221", "triceps"):    0.45,

    # ── Rear Delt Fly ────────────────────────────────────────────────────────
    # Upper back genuinely close to primary for rear delt work
    ("E5988A0A", "upper_back"): 0.60,

    # ── Hip Thrust ───────────────────────────────────────────────────────────
    ("D57C2EC7", "hamstrings"): 0.45,
    ("D57C2EC7", "quadriceps"): 0.30,
    ("D57C2EC7", "adductors"):  0.25,

    # ── Bird Dog ─────────────────────────────────────────────────────────────
    ("BD0AD077", "hamstrings"): 0.40,
    ("BD0AD077", "shoulders"):  0.30,
}

app = Flask(__name__)
app.json_provider_class = NumpyJSONProvider
app.json = NumpyJSONProvider(app)

# ── Cache ──────────────────────────────────────────────────────────────────────

def cache_is_valid() -> bool:
    if not CACHE_FILE.exists():
        return False
    age_hours = (time.time() - CACHE_FILE.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS

def load_cache() -> dict:
    with open(CACHE_FILE) as f:
        return json.load(f)

def save_cache(data: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    print(f"  ✓ Cache saved → {CACHE_FILE}")

# ── Hevy API ───────────────────────────────────────────────────────────────────

def fetch_all_workouts() -> list[dict]:
    headers = {"api-key": API_KEY, "accept": "application/json"}
    workouts, page = [], 1
    print("Fetching workouts", end="", flush=True)
    while True:
        r = requests.get(f"{BASE_URL}/workouts", headers=headers,
                         params={"page": page, "pageSize": PAGE_SIZE})
        r.raise_for_status()
        batch = r.json().get("workouts", [])
        if not batch:
            break
        workouts.extend(batch)
        print(".", end="", flush=True)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    print(f" {len(workouts)} loaded.")
    return workouts

def fetch_templates(template_ids: set) -> dict:
    headers = {"api-key": API_KEY, "accept": "application/json"}
    cache = {}
    ids = [t for t in template_ids if t]
    print(f"Fetching {len(ids)} exercise templates", end="", flush=True)
    for tid in ids:
        try:
            r = requests.get(f"{BASE_URL}/exercise_templates/{tid}",
                             headers=headers, timeout=10)
            if r.status_code == 200:
                t = r.json().get("exercise_template", r.json())
                cache[tid] = {
                    "primary":   t.get("primary_muscle_group") or "",
                    "secondary": t.get("secondary_muscle_groups") or [],
                }
            else:
                cache[tid] = {"primary": "", "secondary": []}
        except Exception:
            cache[tid] = {"primary": "", "secondary": []}
        print(".", end="", flush=True)
    print(" done.")
    return cache

def fetch_fresh_data() -> dict:
    workouts = fetch_all_workouts()
    template_ids = {
        ex.get("exercise_template_id", "")
        for w in workouts for ex in w.get("exercises", [])
    }
    templates = fetch_templates(template_ids)
    payload = {
        "workouts":   workouts,
        "templates":  templates,
        "fetched_at": datetime.now().isoformat(),
    }
    save_cache(payload)
    return payload

def get_data() -> dict:
    if cache_is_valid():
        print("  Using cached data (skip API).")
        return load_cache()
    print("  Cache miss — fetching from Hevy API...")
    return fetch_fresh_data()

# ── Muscle classification ──────────────────────────────────────────────────────

def classify_muscle(name: str, template: dict) -> str:
    raw = template.get("primary", "")
    if raw:
        m = MUSCLE_NORMALISE.get(raw.lower().strip())
        if m:
            return m
    lower = name.lower()
    for kw, grp in sorted(MUSCLE_MAP_FALLBACK.items(), key=lambda x: -len(x[0])):
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
            name   = ex.get("title", "Unknown")
            tid    = ex.get("exercise_template_id", "")
            tmpl   = templates.get(tid, {})
            muscle     = classify_muscle(name, tmpl)
            muscle_raw = tmpl.get("primary", "") or classify_muscle_raw(name, tmpl)
            
            secondary_raws = tmpl.get("secondary", [])

            for s in ex.get("sets", []):
                weight = s.get("weight_kg") or 0.0
                reps   = s.get("reps") or 0
                if reps == 0:
                    continue
                vol  = weight * reps
                e1rm = epley(weight, reps)

                # Primary muscle — full volume
                rows.append({
                    "date":       date,
                    "exercise":   name,
                    "muscle":     muscle,
                    "muscle_raw": muscle_raw,
                    "weight_kg":  weight,
                    "reps":       reps,
                    "volume":     vol,
                    "e1rm":       e1rm,
                    "set_type":   s.get("set_type", "normal"),
                    "is_secondary": False,
                })
                
                # For upper_back exercises, also count traps and rhomboids at full volume
                # since Hevy uses upper_back as a catch-all for the entire upper back complex
                if muscle_raw == 'upper_back':
                    for also in ['traps', 'rhomboids']:
                        also_normalised = MUSCLE_NORMALISE.get(also, "")
                        if also_normalised:
                            rows.append({
                                "date":         date,
                                "exercise":     name,
                                "muscle":       also_normalised,
                                "muscle_raw":   also,
                                "weight_kg":    weight,
                                "reps":         reps,
                                "volume":       vol,
                                "e1rm":         0.0,
                                "set_type":     s.get("set_type", "normal"),
                                "is_secondary": False,
                            })

                # Secondary muscles — 50% volume, no e1rm tracking
                for sec_raw in secondary_raws:
                    sec_raw_clean  = sec_raw.lower().strip()
                    sec_normalised = MUSCLE_NORMALISE.get(sec_raw_clean, "")
                    if not sec_normalised:
                        continue
                    sec_fraction = SECONDARY_WEIGHTS.get((tid, sec_raw_clean), 0.5)
                    rows.append({
                        "date":         date,
                        "exercise":     name,
                        "muscle":       sec_normalised,
                        "muscle_raw":   sec_raw_clean,
                        "weight_kg":    weight,
                        "reps":         reps,
                        "volume":       round(vol * sec_fraction, 1),
                        "e1rm":         0.0,
                        "set_type":     s.get("set_type", "normal"),
                        "is_secondary": True,
                    })
                    
                    # When upper_back appears as secondary, also credit traps and rhomboids at same 50% weight
                    if sec_raw_clean == 'upper_back':
                        for also in ['traps', 'rhomboids']:
                            also_normalised = MUSCLE_NORMALISE.get(also, "")
                            if also_normalised:
                                rows.append({
                                    "date":         date,
                                    "exercise":     name,
                                    "muscle":       also_normalised,
                                    "muscle_raw":   also,
                                    "weight_kg":    weight,
                                    "reps":         reps,
                                    "volume":       round(vol * sec_fraction, 1),
                                    "e1rm":         0.0,
                                    "set_type":     s.get("set_type", "normal"),
                                    "is_secondary": True,
                                })

                    
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

    acute_start   = ref_date - pd.Timedelta(days=7)
    chronic_start = ref_date - pd.Timedelta(days=42)

    acute_vol = ex[ex["date"] > acute_start]["volume"].sum()

    # Compute weekly volumes over the chronic window
    chronic_ex = ex[(ex["date"] > chronic_start) & (ex["date"] <= ref_date)].copy()
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

    best_e1rm  = ex["e1rm"].max()
    last_date  = ex["date"].max()
    last_sess  = ex[ex["date"] == last_date]
    is_bw      = last_sess["weight_kg"].max() == 0
    days_since = max((pd.Timestamp.now() - last_date).days, 0)

    top_weight = 0 if is_bw else last_sess["weight_kg"].max()
    top_reps   = int(last_sess["reps"].max()) if is_bw else \
                 int(last_sess.loc[last_sess["weight_kg"].idxmax(), "reps"])

    if days_since > STALE_DAYS:
        return {
            "exercise":    exercise,
            "last_weight": 0 if is_bw else round_to_half(top_weight),
            "last_reps":   top_reps,
            "best_e1rm":   round_to_half(best_e1rm),
            "rec_weight":  0 if is_bw else round_to_half(top_weight),
            "rec_reps":    top_reps,
            "deload":      False,
            "days_since":  int(days_since),
            "is_bw":       bool(is_bw),
            "status":      "returning",
            "note":        f"Returning after {days_since}d — resume last load",
        }

    ex["week"] = ex["date"].dt.to_period("W")
    weekly_vol = ex.groupby("week")["volume"].sum().sort_index()
    acwr = calc_acwr(df, exercise, last_date)
    deload = acwr > 1.3 and days_since <= STALE_DAYS

    if deload:
        # Suggest pulling back to ~80% of current load
        rec_weight = round_to_half(top_weight * 0.8) if not is_bw else 0
        rec_reps   = max(1, int(top_reps * 0.8))
        note       = f"⚠ ACWR {acwr} — reduce load, risk of overreaching"
        status     = "deload"
    elif is_bw:
        rec_weight, rec_reps = 0, top_reps + 1
        note   = f"Bodyweight — target {top_reps + 1} reps"
        status = "progress"
    elif top_reps >= UPPER_REP_TARGET:
        rec_weight = round_to_half(top_weight + WEIGHT_INCREMENT)
        rec_reps   = REP_RESET_AFTER_BUMP
        note       = f"Hit {top_reps} reps — go up to {rec_weight} kg"
        status     = "bump"
    else:
        rec_weight = round_to_half(top_weight)
        rec_reps   = top_reps + 1
        note       = f"Same weight — target {top_reps + 1} reps"
        status     = "progress"

    return {
        "exercise":    exercise,
        "last_weight": 0 if is_bw else round_to_half(top_weight),
        "last_reps":   int(top_reps),
        "best_e1rm":   round_to_half(float(best_e1rm)),
        "rec_weight":  float(rec_weight),
        "rec_reps":    int(rec_reps),
        "deload":      bool(deload),
        "acwr":        float(acwr),
        "days_since":  int(days_since),
        "is_bw":       bool(is_bw),
        "status":      status,
        "note":        note,
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

    ranked  = rank_exercises(df)
    top_exs = ranked[:TOP_N]
    preds   = [p for ex in ranked if (p := predict_next(df, ex))]

    # Volume over time — all exercises
    df["week"] = df["date"].dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
    vol_data = {}
    for ex in ranked:
        sub = df[df["exercise"] == ex].groupby("week")["volume"].sum()
        vol_data[ex] = {"weeks": list(sub.index), "values": [round(v,1) for v in sub.values]}

    # e1RM over time — all exercises
    e1rm_data = {}
    for ex in ranked:
        sub = df[(df["exercise"] == ex) & (df["e1rm"] > 0)]
        sub = sub.groupby("date")["e1rm"].max().reset_index()
        e1rm_data[ex] = {
            "dates":  [d.strftime("%Y-%m-%d") for d in sub["date"]],
            "values": [round(v,1) for v in sub["e1rm"]],
        }

    # Muscle breakdown — send as daily series so frontend can filter by window
    muscle_daily = (
        df.drop_duplicates(["date", "muscle"])
          .assign(date_str=df["date"].dt.strftime("%Y-%m-%d"))
    )
    # Per-date volume per muscle
    muscle_vol_daily = (
        df.groupby([df["date"].dt.strftime("%Y-%m-%d"), "muscle"])["volume"]
          .sum().reset_index()
    )
    muscle_vol_daily.columns = ["date", "muscle", "volume"]

    # All unique muscles, stable order by all-time volume
    all_muscles = df.groupby("muscle")["volume"].sum().sort_values(ascending=False).index.tolist()

    # Build per-muscle date→volume and date→session_count series
    # Muscle breakdown — send as daily time series using raw muscle keys
    muscle_daily_raw = (
        df.drop_duplicates(["date", "muscle_raw"])
          .assign(date_str=df["date"].dt.strftime("%Y-%m-%d"))
    )
    muscle_vol_daily_raw = (
        df.groupby([df["date"].dt.strftime("%Y-%m-%d"), "muscle_raw"])["volume"]
          .sum().reset_index()
    )
    muscle_vol_daily_raw.columns = ["date", "muscle", "volume"]

    all_muscles_raw = df.groupby("muscle_raw")["volume"].sum().sort_values(ascending=False).index.tolist()

    muscle_series = {}
    for m in all_muscles_raw:
        vol_sub  = muscle_vol_daily_raw[muscle_vol_daily_raw["muscle"] == m]

        # Primary sessions — full count
        primary_dates = (
            df[(df["muscle_raw"] == m) & (~df["is_secondary"])]
            ["date"].dt.strftime("%Y-%m-%d").drop_duplicates().tolist()
        )
        # Secondary sessions — only dates not already covered by primary
        secondary_dates = (
            df[(df["muscle_raw"] == m) & (df["is_secondary"])]
            ["date"].dt.strftime("%Y-%m-%d").drop_duplicates()
        )
        secondary_only = [d for d in secondary_dates if d not in set(primary_dates)]

        # Combine: primary dates + secondary-only dates each weighted 0.5
        # We encode this as a list of (date, weight) but since the frontend
        # just counts dates, we duplicate primary and send secondary separately
        freq_dates = primary_dates + secondary_only  # secondary_only counted at 0.5 in frontend

        muscle_series[m] = {
            "vol_dates":        list(vol_sub["date"]),
            "vol_values":       [round(v, 1) for v in vol_sub["volume"]],
            "freq_dates":       freq_dates,
            "freq_dates_secondary": secondary_only,  # frontend uses this to apply 0.5 weight
        }
        
    # Calendar heatmap data — per day: set count, volume, muscles hit
    df_primary = df[~df["is_secondary"]].copy()
    cal_days = df_primary.groupby(df_primary["date"].dt.strftime("%Y-%m-%d")).agg(
        sets=("reps", "count"),
        volume=("volume", "sum"),
    ).reset_index()
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
            "sets":    int(row["sets"]),
            "volume":  round(row["volume"], 1),
            "muscles": row["muscles"] if isinstance(row["muscles"], list) else [],
        }
        for _, row in cal_merged.iterrows()
    }

    # PRs for top exercises — send both max-weight and max-e1rm sets
    prs = []
    for ex in top_exs:
        sub = df[df["exercise"] == ex]
        if sub.empty or sub["weight_kg"].max() == 0:
            continue

        row_wt   = sub.loc[sub["weight_kg"].idxmax()]
        row_e1rm = sub.loc[sub["e1rm"].idxmax()]
        row_vol  = sub.loc[sub["volume"].idxmax()]

        prs.append({
            "exercise": ex,
            "by_weight": {
                "weight":   round(row_wt["weight_kg"], 1),
                "reps":     int(row_wt["reps"]),
                "e1rm":     round(row_wt["e1rm"], 1),
                "volume":   round(row_wt["volume"], 1),
                "date":     row_wt["date"].strftime("%d %b %Y"),
                "date_iso": row_wt["date"].strftime("%Y-%m-%d"),
            },
            "by_e1rm": {
                "weight":   round(row_e1rm["weight_kg"], 1),
                "reps":     int(row_e1rm["reps"]),
                "e1rm":     round(row_e1rm["e1rm"], 1),
                "volume":   round(row_e1rm["volume"], 1),
                "date":     row_e1rm["date"].strftime("%d %b %Y"),
                "date_iso": row_e1rm["date"].strftime("%Y-%m-%d"),
            },
            "by_vol": {
                "weight":   round(row_vol["weight_kg"], 1),
                "reps":     int(row_vol["reps"]),
                "e1rm":     round(row_vol["e1rm"], 1),
                "volume":   round(row_vol["volume"], 1),
                "date":     row_vol["date"].strftime("%d %b %Y"),
                "date_iso": row_vol["date"].strftime("%Y-%m-%d"),
            },
        })

    total_vol_t = round(df["volume"].sum() / 1000, 1)

    # Best time/day to train
    df_primary = df[~df["is_secondary"]].copy()
    df_primary["hour"]       = pd.to_datetime(df_primary["date"]).dt.hour
    df_primary["day_of_week"] = pd.to_datetime(df_primary["date"]).dt.dayofweek  # 0=Mon

    # Per-session stats — one row per unique date
    sessions = (
        df_primary.groupby("date")
        .agg(sets=("reps","count"), volume=("volume","sum"))
        .reset_index()
    )
    sessions["hour"]        = sessions["date"].dt.hour
    sessions["day_of_week"] = sessions["date"].dt.dayofweek
    sessions["date_str"]    = sessions["date"].dt.strftime("%Y-%m-%d")

    timing_data = [
        {
            "date":    row["date_str"],
            "day":     int(row["day_of_week"]),
            "hour":    int(row["hour"]),
            "sets":    int(row["sets"]),
            "volume":  round(row["volume"], 1),
        }
        for _, row in sessions.iterrows()
    ]

    return {
        "summary": {
            "workouts":   int(df["date"].dt.date.nunique()),
            "volume_t":   total_vol_t,
            "exercises":  int(df["exercise"].nunique()),
            "date_range": f"{df['date'].min().strftime('%b %Y')} – {df['date'].max().strftime('%b %Y')}",
            "fetched_at": raw.get("fetched_at", ""),
        },
        "secondary_weights": {f"{tid}|{muscle}": weight 
                        for (tid, muscle), weight in SECONDARY_WEIGHTS.items()},
        "exercises":     top_exs,
        "volume":        vol_data,
        "e1rm":          e1rm_data,
        "muscle_series": muscle_series,
        "muscles":       all_muscles_raw,
        "prs":           prs,
        "predictions":   preds,
        "calendar":      calendar,
        "timing":        timing_data,
    }

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def api_data():
    try:
        return jsonify(build_api_payload(get_data()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Bust cache and re-fetch everything from Hevy."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
        return jsonify(build_api_payload(fetch_fresh_data()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cache-info")
def cache_info():
    if not CACHE_FILE.exists():
        return jsonify({"exists": False})
    age_h = (time.time() - CACHE_FILE.stat().st_mtime) / 3600
    raw   = load_cache()
    return jsonify({
        "exists":     True,
        "age_hours":  round(age_h, 1),
        "fetched_at": raw.get("fetched_at", ""),
        "valid":      age_h < CACHE_MAX_AGE_HOURS,
    })

@app.route("/workout/<date>")
def workout_detail(date):
    """Serve the workout detail page — the JS fetches /api/workout/<date>."""
    return render_template("workout.html", date=date)

@app.route("/api/workout/<date>")
def api_workout(date):
    try:
        from datetime import date as date_type, timedelta, datetime
        raw       = get_data()
        templates = raw.get("templates", {})
        workouts  = raw.get("workouts", [])

        # ── Pass 1: build all-time PRs chronologically ─────────────────────────
        # For each exercise, record the value and the date it was FIRST achieved.
        pr_weight = {}  # name -> (best_weight, first_date_str)
        pr_e1rm   = {}  # name -> (best_e1rm,   first_date_str)
        pr_vol    = {}  # name -> (best_vol,     first_date_str)

        for w in sorted(workouts, key=lambda x: x.get("start_time", "")):
            w_date_str = w.get("start_time", "")[:10]
            for ex in w.get("exercises", []):
                name = ex.get("title", "Unknown")
                for s in ex.get("sets", []):
                    if s.get("set_type", "normal") != "normal":
                        continue
                    weight = s.get("weight_kg") or 0.0
                    reps   = s.get("reps") or 0
                    e1rm   = epley(weight, reps)
                    vol    = weight * reps
                    if weight > pr_weight.get(name, (0, ""))[0]:
                        pr_weight[name] = (weight, w_date_str)
                    if e1rm > pr_e1rm.get(name, (0, ""))[0]:
                        pr_e1rm[name] = (e1rm, w_date_str)
                    if vol > pr_vol.get(name, (0, ""))[0]:
                        pr_vol[name] = (vol, w_date_str)

        # ── Pass 2: find workouts in the requested window ──────────────────────
        target      = date_type.fromisoformat(date)
        search_week = request.args.get("range") == "week"
        if search_week:
            week_start = target - timedelta(days=target.weekday())
            week_end   = week_start + timedelta(days=6)
            def in_window(d): return week_start <= d <= week_end
        else:
            def in_window(d): return d == target

        def parse_date(ts):
            if not ts: return None
            try:    return date_type.fromisoformat(ts[:10])
            except: return None

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
                        (datetime.fromisoformat(e) - datetime.fromisoformat(s))
                        .total_seconds() / 60
                    )
                except: pass

            # Track which exercises have already received a PR badge this workout
            awarded_pr_weight = set()
            awarded_pr_e1rm   = set()
            awarded_pr_vol    = set()

            exercises  = []
            total_vol  = 0.0
            for ex in w.get("exercises", []):
                name   = ex.get("title", "Unknown")
                tid    = ex.get("exercise_template_id", "")
                tmpl   = templates.get(tid, {})
                muscle = classify_muscle(name, tmpl)
                muscle_raw = tmpl.get("primary", "").lower().strip() or classify_muscle_raw(name, tmpl)
                secondary_raws = [s.lower().strip() for s in tmpl.get("secondary", [])]


                sets, ex_vol = [], 0.0

                for s in ex.get("sets", []):
                    weight = s.get("weight_kg") or 0.0
                    reps   = s.get("reps") or 0
                    vol    = weight * reps
                    ex_vol += vol
                    e1rm   = round(epley(weight, reps), 1)

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

                    if is_pr_weight: awarded_pr_weight.add(name)
                    if is_pr_e1rm:   awarded_pr_e1rm.add(name)
                    if is_pr_vol:    awarded_pr_vol.add(name)

                    sets.append({
                        "type":      s.get("set_type", "normal"),
                        "weight_kg": round(weight, 2),
                        "reps":      reps,
                        "rpe":       s.get("rpe"),
                        "e1rm":      e1rm,
                        "volume":    round(vol, 1),
                        "pr_weight": is_pr_weight,
                        "pr_e1rm":   is_pr_e1rm,
                        "pr_vol":    is_pr_vol,
                    })

                total_vol += ex_vol
                exercises.append({
                    "name":   name,
                    "muscle": muscle,
                    "muscle_raw": muscle_raw,
                    "secondary_raws": secondary_raws,
                    "template_id":    tid,
                    "notes":  ex.get("notes", ""),
                    "sets":   sets,
                    "volume": round(ex_vol, 1),
                })

            day_workouts.append({
                "id":           w.get("id", ""),
                "title":        w.get("title", "Workout"),
                "start_time":   w.get("start_time", ""),
                "end_time":     w.get("end_time", ""),
                "duration_min": duration_min,
                "description":  w.get("description", ""),
                "exercises":    exercises,
                "total_volume": round(total_vol, 1),
            })

        if not day_workouts:
            label = f"the week of {date}" if search_week else date
            return jsonify({"error": f"No workout found for {label}"}), 404

        day_workouts.sort(key=lambda x: x["start_time"])
        return jsonify({
            "date":               date,
            "workouts":           day_workouts,
            "secondary_weights":  {f"{tid}|{muscle}": weight
                                   for (tid, muscle), weight in SECONDARY_WEIGHTS.items()},
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(Path(__file__).parent / "static", filename)

if __name__ == "__main__":
    if not API_KEY:
        sys.exit("No HEVY_API_KEY found. Add it to .env or export it.")
    print("⚡  Hevy Dashboard → http://localhost:5000")
    app.run(debug=True, port=5000)