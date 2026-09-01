# Hevy Training Dashboard

A self-hosted dashboard for your [Hevy](https://hevy.com) workout data. Pulls your full training history via the Hevy API and gives you charts, muscle heatmaps, PR tracking, and next-session recommendations in one place.

**Note:** This is a personal project I built for my own training. It's shared as-is, and I'm not actively maintaining it or responding to issues. Feel free to fork it and adapt it to your needs though.

![Dashboard](images/frontpage.png)

![Workout detail](images/workout.png)

---

## Features

- **Training calendar** — GitHub-style heatmap of every session, hover for volume and muscles hit
- **Volume over time** — weekly volume per exercise, filterable by 1M / 3M / 1Y
- **Estimated 1-rep max** — e1RM over time using the Epley formula, with Gaussian smoothing
- **Muscle heatmaps** — SVG body map coloured by volume and session frequency, with secondary muscle attribution
- **Personal records** — best weight, e1RM, and single-set volume per exercise, with PR badges on workout detail pages
- **Next session planner** — per-exercise recommendations based on your last session, with ACWR-based deload detection
- **Strength progress panel** — e1RM and volume change vs 30 days ago across all exercises
- **Exercise detail pages** — full progression history, charts, PRs and muscle map per exercise
- **Workout detail pages** — full set-by-set breakdown for any session
- **Month view** — summary and muscle heatmap for any calendar month
- **Best time/day scatter plot** — see when your best sessions tend to happen
- **Light / dark mode**
- **SQLite database** — data stored locally in `hevy.db`, incremental sync on refresh

---

## Requirements

- Python 3.10+
- A [Hevy](https://hevy.com) account
- A Hevy API key (available in the Hevy app settings)

---

## Installation

```bash
git clone https://github.com/bavadeve/hevy-dashboard.git
cd hevy-dashboard
pip install flask requests pandas numpy python-dotenv
```

Create a `.env` file in the project root:

```
HEVY_API_KEY=your_api_key_here
```

---

## Running

```bash
python app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000).

On first load it fetches your full workout history from the Hevy API and stores it in `hevy.db`. Click **Refresh** in the UI to pull in any new workouts.

---

## Project structure

```
hevy-dashboard/
├── app.py               # Flask backend, data processing, API endpoints
├── hevy_db.py           # SQLite database layer, schema, insert and compute functions
├── hevy_migrate.py      # One-time migration from cache.json to hevy.db
├── templates/
│   ├── index.html       # Main dashboard
│   ├── workout.html     # Workout detail page
│   ├── exercise.html    # Exercise detail page
│   └── month.html       # Month view page
├── static/
│   └── muscles.svg      # Body map SVG for muscle heatmaps
├── hevy.db              # SQLite database (auto-created, gitignored)
└── .env                 # Your API key (gitignored)
```

---

## Configuration

All the constants you'd want to tweak are at the top of `app.py`:

| Constant | Default | Description |
|---|---|---|
| `TOP_N` | `8` | Number of exercises shown in charts and the PR panel |
| `STALE_DAYS` | `21` | Days without a session before an exercise is marked inactive |
| `UPPER_REP_TARGET` | `12` | Rep ceiling before the weight gets bumped |
| `WEIGHT_INCREMENT` | `2.0` | kg added on a weight bump (adjust for your equipment) |
| `REP_RESET_AFTER_BUMP` | `8` | Target reps after bumping weight |

---

## Muscle attribution

Volume is credited to both primary and secondary muscles. Secondary muscles get 50% of the primary volume by default, with per-exercise overrides in the `SECONDARY_WEIGHTS` dict in `app.py` for cases where the secondary involvement is clearly higher or lower.

Hevy uses `upper_back` as a catch-all, so the dashboard splits it into `traps` and `rhomboids` separately.

---

## Database

All workout data is stored in `hevy.db`. On refresh, only workouts newer than the latest one in the database are fetched — so subsequent refreshes are fast regardless of how much history you have.

If you're migrating from an older version that used `cache.json`, run:

```bash
python hevy_migrate.py
```

---

## .gitignore

```
.env
hevy.db
__pycache__/
*.pyc
```

---

## Notes

Not affiliated with or endorsed by Hevy.