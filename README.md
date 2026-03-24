# Hevy Training Dashboard

A self-hosted dashboard for your [Hevy](https://hevy.com) workout data. Pulls your full training history via the Hevy API and gives you charts, muscle heatmaps, PR tracking, and next-session recommendations in one place.

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
- **Workout detail pages** — full set-by-set breakdown for any session
- **Best time/day scatter plot** — see when your best sessions tend to happen
- **Light / dark mode**
- **Local caching** — data is fetched once and cached for 24 hours

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

Then open [http://localhost:5000](http://localhost:5000).

On first load it fetches your full workout history from the Hevy API and saves it to `cache.json`. After that it reads from the cache. Click **Refresh** in the UI to re-fetch, or just delete `cache.json` manually.

---

## Project structure

```
hevy-dashboard/
├── app.py               # Flask backend, data processing, API endpoints
├── templates/
│   ├── index.html       # Main dashboard
│   └── workout.html     # Workout detail page
├── static/
│   └── muscles.svg      # Body map SVG for muscle heatmaps
├── cache.json           # Auto-generated on first run (gitignored)
└── .env                 # Your API key (gitignored)
```

---

## Configuration

All the constants you'd want to tweak are at the top of `app.py`:

| Constant | Default | Description |
|---|---|---|
| `TOP_N` | `8` | Number of exercises shown in charts and the PR panel |
| `CACHE_MAX_AGE_HOURS` | `24` | Cache expiry in hours |
| `STALE_DAYS` | `21` | Days without a session before an exercise is marked inactive |
| `UPPER_REP_TARGET` | `12` | Rep ceiling before the weight gets bumped |
| `WEIGHT_INCREMENT` | `2.0` | kg added on a weight bump (adjust for your equipment) |
| `REP_RESET_AFTER_BUMP` | `8` | Target reps after bumping weight |

---

## Muscle attribution

Volume is credited to both primary and secondary muscles. Secondary muscles get 50% of the primary volume by default, with per-exercise overrides in the `SECONDARY_WEIGHTS` dict in `app.py` for cases where the secondary involvement is clearly higher or lower.

Hevy uses `upper_back` as a catch-all, so the dashboard splits it into `traps` and `rhomboids` separately.

---

## Caching

The Hevy API is only called when:

1. There's no `cache.json` yet
2. You click **Refresh** or the cache is older than `CACHE_MAX_AGE_HOURS`

Everything else runs locally.

---

## .gitignore

```
.env
cache.json
__pycache__/
*.pyc
```

---

## Notes

Not affiliated with or endorsed by Hevy.