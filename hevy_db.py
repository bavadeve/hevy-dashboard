"""
hevy_db.py — SQLite database layer for the Hevy dashboard.
Mirrors the pattern of db.py from the running dashboard.
"""

import sqlite3
import json
from datetime import datetime, date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = "hevy.db"

# ── Config — keep in sync with app.py ─────────────────────────────────────────
TOP_N = 8
STALE_DAYS = 21
DELOAD_THRESHOLD = 0.90
UPPER_REP_TARGET = 12
WEIGHT_INCREMENT = 2.0
REP_RESET_AFTER_BUMP = 8

# ── Muscle Maps ────────────────────────────────────────────
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
    "upper_back": "Traps",
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

SECONDARY_WEIGHTS = {
    ("72CFFAD5", "glutes"): 0.75,
    ("72CFFAD5", "lower_back"): 0.60,
    ("72CFFAD5", "upper_back"): 0.30,
    ("72CFFAD5", "lats"): 0.20,
    ("937292AB", "glutes"): 0.75,
    ("937292AB", "lower_back"): 0.50,
    ("5F4E6DD3", "hamstrings"): 0.80,
    ("5F4E6DD3", "quadriceps"): 0.60,
    ("5F4E6DD3", "lower_back"): 0.60,
    ("5F4E6DD3", "upper_back"): 0.35,
    ("5F4E6DD3", "lats"): 0.25,
    ("5F4E6DD3", "traps"): 0.25,
    ("B5D3A742", "glutes"): 0.70,
    ("B5D3A742", "hamstrings"): 0.40,
    ("BF6ECE89", "glutes"): 0.65,
    ("BF6ECE89", "hamstrings"): 0.35,
    ("DCFF3E9F", "hamstrings"): 0.45,
    ("DCFF3E9F", "glutes"): 0.60,
    ("20C1A3CB", "hamstrings"): 0.40,
    ("20C1A3CB", "glutes"): 0.60,
    ("F1E57334", "upper_back"): 0.70,
    ("F1E57334", "biceps"): 0.40,
    ("F1E57334", "forearms"): 0.20,
    ("23E92538", "lats"): 0.65,
    ("23E92538", "biceps"): 0.40,
    ("23E92538", "forearms"): 0.20,
    ("C732C341", "lats"): 0.65,
    ("C732C341", "biceps"): 0.40,
    ("C732C341", "forearms"): 0.20,
    ("67280085", "chest"): 0.55,
    ("67280085", "upper_back"): 0.40,
    ("67280085", "triceps"): 0.20,
    ("07B38369", "triceps"): 0.55,
    ("07B38369", "shoulders"): 0.35,
    ("3601968B", "triceps"): 0.55,
    ("3601968B", "shoulders"): 0.30,
    ("756EE329", "triceps"): 0.60,
    ("756EE329", "shoulders"): 0.25,
    ("392887AA", "triceps"): 0.55,
    ("392887AA", "shoulders"): 0.30,
    ("6AC96645", "triceps"): 0.50,
    ("878CD1D0", "triceps"): 0.50,
    ("A69FF221", "triceps"): 0.45,
    ("E5988A0A", "upper_back"): 0.60,
    ("D57C2EC7", "hamstrings"): 0.45,
    ("D57C2EC7", "quadriceps"): 0.30,
    ("D57C2EC7", "adductors"): 0.25,
    ("BD0AD077", "hamstrings"): 0.40,
    ("BD0AD077", "shoulders"): 0.30,
}


# ── Utilities ──────────────────────────────────────────────────────────────────


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def epley(weight: float, reps: int) -> float:
    if weight <= 0 or reps == 0:
        return 0.0
    return weight if reps == 1 else weight * (1 + reps / 30)


def round_to_half(v: float) -> float:
    return round(v * 2) / 2


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
    raw = template.get("primary", "")
    if raw:
        return raw.lower().strip()
    lower = name.lower()
    for kw in sorted(MUSCLE_MAP_FALLBACK.keys(), key=lambda x: -len(x)):
        if kw in lower:
            return kw
    return "other"


# ── Schema ─────────────────────────────────────────────────────────────────────


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workouts (
            hevy_id     TEXT PRIMARY KEY,
            title       TEXT,
            start_time  TEXT,
            end_time    TEXT,
            description TEXT,
            raw_data    TEXT
        );

        CREATE TABLE IF NOT EXISTS exercises (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_id  TEXT REFERENCES workouts(hevy_id),
            title       TEXT,
            template_id TEXT,
            notes       TEXT,
            sort_order  INTEGER,
            raw_data    TEXT
        );

        CREATE TABLE IF NOT EXISTS sets (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_id      INTEGER REFERENCES exercises(id),
            set_index        INTEGER,
            set_type         TEXT,
            weight_kg        REAL,
            reps             INTEGER,
            duration_seconds INTEGER,
            volume           REAL,
            e1rm             REAL
        );

        CREATE TABLE IF NOT EXISTS templates (
            template_id       TEXT PRIMARY KEY,
            name              TEXT,
            primary_muscle    TEXT,
            secondary_muscles TEXT,
            raw_data          TEXT
        );

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_workouts_start_time   ON workouts(start_time);
        CREATE INDEX IF NOT EXISTS idx_exercises_workout_id  ON exercises(workout_id);
        CREATE INDEX IF NOT EXISTS idx_exercises_template_id ON exercises(template_id);
        CREATE INDEX IF NOT EXISTS idx_sets_exercise_id      ON sets(exercise_id);
        
        CREATE TABLE IF NOT EXISTS computed_payload (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


# ── Insert functions ───────────────────────────────────────────────────────────


def insert_workouts(conn, workouts: list):
    """Insert new workouts, exercises and sets. Skips already-stored workouts."""
    existing = {
        r[0] for r in conn.execute("SELECT hevy_id FROM workouts").fetchall()
    }
    inserted = 0

    for w in workouts:
        wid = w.get("id", "")
        if wid in existing:
            continue

        conn.execute(
            """INSERT OR IGNORE INTO workouts (hevy_id, title, start_time, end_time, description, raw_data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                wid,
                w.get("title", ""),
                w.get("start_time", ""),
                w.get("end_time", ""),
                w.get("description", ""),
                json.dumps(w),
            ),
        )

        for sort_order, ex in enumerate(w.get("exercises", [])):
            cur = conn.execute(
                """INSERT INTO exercises (workout_id, title, template_id, notes, sort_order, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    wid,
                    ex.get("title", ""),
                    ex.get("exercise_template_id", ""),
                    ex.get("notes", ""),
                    sort_order,
                    json.dumps(ex),
                ),
            )
            ex_id = cur.lastrowid

            for s in ex.get("sets", []):
                weight = s.get("weight_kg") or 0.0
                reps = s.get("reps") or 0
                dur = s.get("duration_seconds") or 0
                vol = weight * reps
                e1rm_v = epley(weight, reps) if weight > 0 and reps > 0 else 0.0
                conn.execute(
                    """INSERT INTO sets (exercise_id, set_index, set_type, weight_kg, reps,
                                        duration_seconds, volume, e1rm)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ex_id,
                        s.get("index", 0),
                        s.get("set_type", s.get("type", "normal")),
                        weight,
                        reps,
                        dur,
                        round(vol, 2),
                        round(e1rm_v, 2),
                    ),
                )

        inserted += 1

    print(
        f"  Inserted {inserted} new workouts ({len(existing)} already present)"
    )
    return inserted


def insert_templates(conn, templates: dict):
    """Insert templates, skipping already-stored ones."""
    existing = {
        r[0]
        for r in conn.execute("SELECT template_id FROM templates").fetchall()
    }
    inserted = 0

    for tid, tmpl in templates.items():
        if tid in existing:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO templates (template_id, name, primary_muscle, secondary_muscles, raw_data)
               VALUES (?, ?, ?, ?, ?)""",
            (
                tid,
                tmpl.get("name", ""),
                tmpl.get("primary", ""),
                json.dumps(tmpl.get("secondary", [])),
                json.dumps(tmpl),
            ),
        )
        inserted += 1

    print(
        f"  Inserted {inserted} new templates ({len(existing)} already present)"
    )


def get_latest_workout_time(conn) -> str | None:
    """Return the start_time of the most recent workout, or None."""
    row = conn.execute(
        "SELECT MAX(start_time) as latest FROM workouts"
    ).fetchone()
    return row["latest"] if row and row["latest"] else None


# ── Build DataFrame from DB ─────────────────────────────────────────────────


def build_dataframe(conn) -> pd.DataFrame:
    """
    Build the main analytics DataFrame from DB.
    Mirrors build_dataframe() in app.py exactly.
    """
    rows_query = """
        SELECT
            w.start_time,
            e.title        AS exercise,
            e.template_id,
            t.primary_muscle,
            t.secondary_muscles,
            s.set_type,
            s.weight_kg,
            s.reps,
            s.duration_seconds,
            s.volume,
            s.e1rm
        FROM sets s
        JOIN exercises e ON s.exercise_id = e.id
        JOIN workouts  w ON e.workout_id  = w.hevy_id
        LEFT JOIN templates t ON e.template_id = t.template_id
        WHERE s.set_type = 'normal'
          AND (s.reps > 0 OR s.duration_seconds > 0)
        ORDER BY w.start_time
    """
    db_rows = conn.execute(rows_query).fetchall()
    if not db_rows:
        return pd.DataFrame()

    rows = []
    for r in db_rows:
        date_val = pd.to_datetime(r["start_time"], utc=True).tz_localize(None)
        primary = (r["primary_muscle"] or "").lower().strip()
        secondary = json.loads(r["secondary_muscles"] or "[]")
        tid = r["template_id"] or ""
        name = r["exercise"]
        weight = float(r["weight_kg"] or 0)
        reps = int(r["reps"] or 0)
        vol = float(r["volume"] or 0)
        e1rm_val = float(r["e1rm"] or 0)
        dur = int(r["duration_seconds"] or 0)

        # Reconstruct template dict for classify functions
        tmpl = {"primary": primary, "secondary": secondary}
        muscle = classify_muscle(name, tmpl)
        muscle_raw = primary or classify_muscle_raw(name, tmpl)

        # Primary row
        rows.append(
            {
                "date": date_val,
                "exercise": name,
                "muscle": muscle,
                "muscle_raw": muscle_raw,
                "weight_kg": weight,
                "reps": reps,
                "volume": vol,
                "e1rm": e1rm_val,
                "duration_sec": dur,
                "set_type": r["set_type"],
                "is_secondary": False,
            }
        )

        # upper_back split into traps + rhomboids
        if muscle_raw == "upper_back":
            for also in ["traps", "rhomboids"]:
                also_norm = MUSCLE_NORMALISE.get(also, "")
                if also_norm:
                    rows.append(
                        {
                            "date": date_val,
                            "exercise": name,
                            "muscle": also_norm,
                            "muscle_raw": also,
                            "weight_kg": weight,
                            "reps": reps,
                            "volume": vol,
                            "e1rm": 0.0,
                            "duration_sec": 0,
                            "set_type": r["set_type"],
                            "is_secondary": False,
                        }
                    )

        # Secondary rows
        for sec_raw in secondary:
            sec_clean = sec_raw.lower().strip()
            sec_norm = MUSCLE_NORMALISE.get(sec_clean, "")
            if not sec_norm:
                continue
            sec_fraction = SECONDARY_WEIGHTS.get((tid, sec_clean), 0.5)
            rows.append(
                {
                    "date": date_val,
                    "exercise": name,
                    "muscle": sec_norm,
                    "muscle_raw": sec_clean,
                    "weight_kg": weight,
                    "reps": reps,
                    "volume": round(vol * sec_fraction, 1),
                    "e1rm": 0.0,
                    "duration_sec": 0,
                    "set_type": r["set_type"],
                    "is_secondary": True,
                }
            )
            if sec_clean == "upper_back":
                for also in ["traps", "rhomboids"]:
                    also_norm = MUSCLE_NORMALISE.get(also, "")
                    if also_norm:
                        rows.append(
                            {
                                "date": date_val,
                                "exercise": name,
                                "muscle": also_norm,
                                "muscle_raw": also,
                                "weight_kg": weight,
                                "reps": reps,
                                "volume": round(vol * sec_fraction, 1),
                                "e1rm": 0.0,
                                "duration_sec": 0,
                                "set_type": r["set_type"],
                                "is_secondary": True,
                            }
                        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    return df


# ── Exercise ranking ───────────────────────────────────────────────────────────


def rank_exercises(df: pd.DataFrame) -> list[str]:
    """
    Rank exercises by recency score.
    Mirrors rank_exercises() in app.py exactly.
    """
    now = pd.Timestamp.now()
    scores = {}
    for name, grp in df.groupby("exercise"):
        sessions = grp["date"].drop_duplicates()
        scores[name] = sum(1.0 / max((now - d).days, 1) for d in sessions)
    return sorted(scores, key=scores.get, reverse=True)


# ── ACWR ───────────────────────────────────────────────────────────────────────


def calc_acwr(df: pd.DataFrame, exercise: str, ref_date: pd.Timestamp) -> float:
    """
    Acute:Chronic Workload Ratio.
    Mirrors calc_acwr() in app.py exactly.
    """
    ex = df[(df["exercise"] == exercise) & (~df["is_secondary"])].copy()
    if ex.empty:
        return 0.0

    acute_start = ref_date - pd.Timedelta(days=7)
    chronic_start = ref_date - pd.Timedelta(days=42)
    acute_vol = ex[ex["date"] > acute_start]["volume"].sum()

    chronic_ex = ex[
        (ex["date"] > chronic_start) & (ex["date"] <= ref_date)
    ].copy()
    if chronic_ex.empty:
        return 0.0

    chronic_ex["week"] = chronic_ex["date"].dt.to_period("W")
    weekly_vols = chronic_ex.groupby("week")["volume"].sum()
    active_weeks = weekly_vols[weekly_vols > 0]

    if len(active_weeks) < 2:
        return 0.0

    chronic_weekly_avg = active_weeks.mean()
    if chronic_weekly_avg == 0:
        return 0.0

    return round(acute_vol / chronic_weekly_avg, 2)


# ── Predictions ────────────────────────────────────────────────────────────────


def predict_next(df: pd.DataFrame, exercise: str) -> dict:
    """
    Predict next session.
    Mirrors predict_next() in app.py exactly.
    """
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
            "best_e1rm": round_to_half(float(best_e1rm)),
            "rec_weight": 0 if is_bw else round_to_half(top_weight),
            "rec_reps": top_reps,
            "deload": False,
            "days_since": int(days_since),
            "is_bw": bool(is_bw),
            "status": "returning",
            "note": f"Returning after {days_since}d — resume last load",
            "acwr": 0.0,
            "deload_rec_weight": 0.0,
            "deload_rec_reps": top_reps,
            "deload_note": "",
        }

    acwr = calc_acwr(df, exercise, last_date)
    deload = acwr > DELOAD_THRESHOLD and days_since <= STALE_DAYS

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
        "status": status,
        "note": note,
        "deload": bool(deload),
        "acwr": float(acwr),
        "deload_rec_weight": float(deload_rec_weight),
        "deload_rec_reps": int(deload_rec_reps),
        "deload_note": deload_note,
        "days_since": int(days_since),
        "is_bw": bool(is_bw),
    }


# ── PR index ───────────────────────────────────────────────────────────────────


def build_pr_index(conn) -> dict:
    """Build all-time PRs from DB. Mirrors build_pr_index() in app.py."""
    pr_weight, pr_e1rm, pr_vol = {}, {}, {}

    rows = conn.execute("""
        SELECT w.start_time, e.title, s.weight_kg, s.reps, s.e1rm, s.volume
        FROM sets s
        JOIN exercises e ON s.exercise_id = e.id
        JOIN workouts  w ON e.workout_id  = w.hevy_id
        WHERE s.set_type = 'normal'
        ORDER BY w.start_time
    """).fetchall()

    for r in rows:
        name = r["title"]
        w_date_str = r["start_time"][:10]
        weight = r["weight_kg"] or 0.0
        e1rm_v = r["e1rm"] or 0.0
        vol = r["volume"] or 0.0

        if weight > pr_weight.get(name, (0, ""))[0]:
            pr_weight[name] = (weight, w_date_str)
        if e1rm_v > pr_e1rm.get(name, (0, ""))[0]:
            pr_e1rm[name] = (e1rm_v, w_date_str)
        if vol > pr_vol.get(name, (0, ""))[0]:
            pr_vol[name] = (vol, w_date_str)

    return {"weight": pr_weight, "e1rm": pr_e1rm, "vol": pr_vol}


def save_payload(conn, payload: dict):
    """Store the full computed payload in the DB."""
    conn.execute(
        "INSERT OR REPLACE INTO computed_payload (key, value) VALUES ('main', ?)",
        (json.dumps(payload, default=str),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('computed_at', ?)",
        (datetime.now().isoformat(),),
    )


def load_payload(conn) -> dict | None:
    """Load the pre-computed payload from the DB, or None if not present."""
    row = conn.execute(
        "SELECT value FROM computed_payload WHERE key = 'main'"
    ).fetchone()
    return json.loads(row[0]) if row else None
