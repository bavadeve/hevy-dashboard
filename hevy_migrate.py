"""
hevy_migrate.py — Migrate cache.json to hevy.db

Run once:
    python hevy_migrate.py

On subsequent runs it only inserts new workouts/templates
(already-stored ones are skipped), so it's safe to re-run.
"""

import json
from pathlib import Path
from datetime import datetime

from hevy_db import (
    init_db,
    get_db,
    insert_workouts,
    insert_templates,
    get_latest_workout_time,
    build_dataframe,
    build_pr_index,
)

CACHE_FILE = Path("cache/cache.json")
DB_PATH = "hevy.db"


def migrate():
    print("Initializing database...")
    init_db()

    if not CACHE_FILE.exists():
        print(f"  No cache.json found at {CACHE_FILE} — nothing to migrate.")
        print(
            "  Run the dashboard and click Refresh to fetch from Hevy API first."
        )
        return

    print(f"Loading {CACHE_FILE}...")
    with open(CACHE_FILE) as f:
        raw = json.load(f)

    workouts = raw.get("workouts", [])
    templates = raw.get("templates", {})
    fetched_at = raw.get("fetched_at", datetime.now().isoformat())

    print(
        f"  Found {len(workouts)} workouts, {len(templates)} templates in cache."
    )

    conn = get_db()

    print("Inserting workouts...")
    insert_workouts(conn, workouts)

    print("Inserting templates...")
    insert_templates(conn, templates)

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("fetched_at", fetched_at),
    )

    conn.commit()

    print("Verifying...")
    n_workouts = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    n_exercises = conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    n_sets = conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    n_templates = conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
    print(
        f"  DB contains: {n_workouts} workouts, {n_exercises} exercises, {n_sets} sets, {n_templates} templates"
    )

    latest = get_latest_workout_time(conn)
    print(f"  Latest workout: {latest}")

    conn.close()
    print("Migration complete.")


def verify():
    """Quick sanity check — compare DB counts vs cache.json."""
    if not CACHE_FILE.exists():
        print("No cache.json to compare against.")
        return

    with open(CACHE_FILE) as f:
        raw = json.load(f)

    cache_workouts = len(raw.get("workouts", []))
    cache_templates = len(raw.get("templates", {}))

    conn = get_db()
    db_workouts = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    db_templates = conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
    db_sets = conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    conn.close()

    print(f"Cache: {cache_workouts} workouts, {cache_templates} templates")
    print(
        f"DB:    {db_workouts} workouts, {db_templates} templates, {db_sets} sets"
    )

    if db_workouts == cache_workouts and db_templates == cache_templates:
        print("✓ Counts match.")
    else:
        print("✗ Mismatch — check for errors above.")


if __name__ == "__main__":
    migrate()
    print()
    verify()
