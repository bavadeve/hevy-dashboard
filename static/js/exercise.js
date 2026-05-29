const FRONT_MAP = {
    'st5': 'shoulders', 'st6': 'abdominals', 'st10': 'biceps',
    'st11': 'chest', 'st12': 'forearms', 'st14': 'quadriceps',
    'st15': 'calves', 'st-forearms': 'forearms',
};

const BACK_MAP = {
    'st5': 'shoulders', 'st6': 'traps', 'st9': 'lats',
    'st10': 'triceps', 'st12': 'hamstrings', 'st15': 'calves',
    'st4': 'glutes', 'st-forearms': 'forearms', 'st-rhomboids': 'rhomboids',
};

const BODY_CLASSES = ['st2', 'st3', 'st7', 'st8', 'st0', 'st1'];

const MUSCLE_NORMALISE = {
    'chest': 'chest', 'upper_chest': 'chest', 'lower_chest': 'chest',
    'quadriceps': 'quadriceps', 'hamstrings': 'hamstrings', 'glutes': 'glutes',
    'adductors': 'quadriceps', 'abductors': 'quadriceps', 'hip_flexors': 'quadriceps',
    'calves': 'calves', 'lats': 'lats', 'upper_back': 'traps',
    'lower_back': 'lats', 'traps': 'traps', 'rhomboids': 'rhomboids',
    'shoulders': 'shoulders', 'front_delts': 'shoulders',
    'side_delts': 'shoulders', 'rear_delts': 'shoulders',
    'biceps': 'biceps', 'triceps': 'triceps', 'forearms': 'forearms',
    'abs': 'abdominals', 'obliques': 'abdominals', 'core': 'abdominals',
};

const STATUS_BADGE = {
    bump: ['BUMP ↑', 'badge-bump'],
    progress: ['PROGRESS', 'badge-progress'],
    deload: ['DELOAD ↓', 'badge-deload'],
    returning: ['RETURN', 'badge-return'],
};

let e1rmChart = null;
let volChart = null;

async function load() {
    try {
        const res = await fetch(`/api/exercise/${encodeURIComponent(NAME)}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        render(data);
        window._exerciseData = data;
    } catch (e) {
        document.getElementById('app').innerHTML =
            `<div class="loading" style="color:var(--red)">ERROR: ${e.message}</div>`;
    }
}

function fmtVol(v) {
    return v >= 1000 ? `${(v / 1000).toFixed(1)}t` : `${Math.round(v)}kg`;
}

function chartDefaults() {
    const isLight = document.documentElement.classList.contains('light');
    const surface = isLight ? '#ffffff' : '#0d1117';
    const border = isLight ? '#dde1e8' : '#1a2233';
    const muted = isLight ? '#8a92a0' : '#4a5568';
    const text = isLight ? '#1a1f2e' : '#e2e8f0';
    const grid = isLight ? '#dde1e8' : '#1a2233';
    const ticks = isLight ? '#8a92a0' : '#4a5568';
    const mono = "'JetBrains Mono', monospace";

    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: surface,
                borderColor: border,
                borderWidth: 1,
                titleColor: muted,
                bodyColor: text,
                padding: 10,
                titleFont: { family: mono, size: 10 },
                bodyFont: { family: mono, size: 12 },
            }
        },
        scales: {
            x: { grid: { color: grid }, ticks: { color: ticks, font: { family: mono, size: 10 }, maxTicksLimit: 6, maxRotation: 0 } },
            y: { grid: { color: grid }, ticks: { color: ticks, font: { family: mono, size: 10 } }, beginAtZero: false },
        },
    };
}
let _muscleVolMap = {};
let _normPrimary = '';
let _primaryRaw = '';

function heatColor(key, isPrimary) {
    const v = _muscleVolMap[key] || 0;
    if (v === 0) return document.documentElement.classList.contains('light') ? '#c8d4e0' : '#1a2233';
    if (isPrimary || v >= 0.8) {
        const t = Math.pow(v, 0.5);
        return `rgb(${Math.round(26 + t * (0 - 26))},${Math.round(34 + t * (255 - 34))},${Math.round(51 + t * (135 - 51))})`;
    } else {
        const t = Math.pow(v, 0.5);
        return `rgb(${Math.round(26 + t * (30 - 26))},${Math.round(34 + t * (120 - 34))},${Math.round(51 + t * (255 - 51))})`;
    }
}

function heatOpacity(key) {
    const v = _muscleVolMap[key] || 0;
    return v === 0 ? 0.15 : Math.max(0.4, v);
}

function applyHeat(svg, classMap) {
    const isLight = document.documentElement.classList.contains('light');
    Object.entries(classMap).forEach(([cls, key]) => {
        const isPrimary = key === _normPrimary || (_primaryRaw === 'upper_back' && (key === 'traps' || key === 'rhomboids'));
        svg.querySelectorAll(`.${cls}`).forEach(el => {
            el.style.fill = heatColor(key, isPrimary);
            el.style.opacity = heatOpacity(key);
            el.setAttribute('data-muscle', key);
        });
    });
    BODY_CLASSES.forEach(cls => {
        svg.querySelectorAll(`.${cls}`).forEach(el => {
            el.style.fill = isLight ? '#c8d4e0' : '#1a2233';
            el.style.opacity = '1';
            el.removeAttribute('data-muscle');
        });
    });
    svg.querySelectorAll('path,ellipse,rect,circle').forEach(el => {
        el.style.stroke = isLight ? '#7a8fa8' : '#0d1117';
        el.style.strokeWidth = '1.5px';
    });
    svg.querySelectorAll('.st13').forEach(el => el.remove());
}

function render(data) {
    // Header
    document.title = `HEVY // ${data.name.toUpperCase()}`;
    document.getElementById('exTitle').textContent = data.name.toUpperCase();
    if (data.muscle) {
        const tag = document.getElementById('muscleTag');
        tag.textContent = data.muscle;
        tag.style.display = '';
    }

    // Summary stats
    const sessions = data.sessions || [];
    const bestE1rm = data.pr?.by_e1rm?.e1rm || 0;
    const bestWeight = data.pr?.by_weight?.weight || 0;
    const totalSess = sessions.length;
    const firstDate = sessions.length ? sessions[sessions.length - 1].date_fmt : '—';
    const lastDate = sessions.length ? sessions[0].date_fmt : '—';

    // Build main content
    const html = `
<div class="summary-bar" style="animation:fadeUp 0.2s ease both">
    <div class="sum-stat">
        <div class="sum-value">${bestE1rm > 0 ? bestE1rm + ' kg' : '—'}</div>
        <div class="sum-label">Best e1RM</div>
    </div>
    <div class="sum-stat">
        <div class="sum-value">${bestWeight > 0 ? bestWeight + ' kg' : '—'}</div>
        <div class="sum-label">Best Weight</div>
    </div>
    <div class="sum-stat">
        <div class="sum-value">${totalSess}</div>
        <div class="sum-label">Sessions</div>
    </div>
    <div class="sum-stat">
        <div class="sum-value" style="font-size:20px;padding-top:6px">${firstDate}</div>
        <div class="sum-label">First Session</div>
    </div>
    <div class="sum-stat">
        <div class="sum-value" style="font-size:20px;padding-top:6px">${lastDate}</div>
        <div class="sum-label">Last Session</div>
    </div>
</div>

<div class="page-body">
    <div class="main-col">

        <!-- e1RM chart -->
        <div class="panel" style="animation:fadeUp 0.25s ease both">
            <div class="panel-title">Estimated 1-Rep Max</div>
            <div class="chart-wrap"><canvas id="e1rmChart"></canvas></div>
        </div>

        <!-- Volume chart -->
        <div class="panel" style="animation:fadeUp 0.3s ease both">
            <div class="panel-title">Weekly Volume</div>
            <div class="chart-wrap"><canvas id="volChart"></canvas></div>
        </div>

        <!-- PRs -->
        ${data.pr && Object.keys(data.pr).length ? `
    <div class="panel" style="animation:fadeUp 0.35s ease both">
        <div class="panel-title">Personal Records</div>
        <div class="pr-grid">
            <a class="pr-card" href="/workout/${data.pr.by_e1rm.date_iso}">
                <div class="pr-type">Best e1RM</div>
                <div class="pr-number">${data.pr.by_e1rm.e1rm} kg</div>
                <div class="pr-sub">${data.pr.by_e1rm.weight} kg × ${data.pr.by_e1rm.reps} reps · ${data.pr.by_e1rm.date}</div>
            </a>
            <a class="pr-card" href="/workout/${data.pr.by_weight.date_iso}">
                <div class="pr-type">Best Weight</div>
                <div class="pr-number">${data.pr.by_weight.weight} kg</div>
                <div class="pr-sub">${data.pr.by_weight.reps} reps · e1RM ${data.pr.by_weight.e1rm} kg · ${data.pr.by_weight.date}</div>
            </a>
            <a class="pr-card" href="/workout/${data.pr.by_vol.date_iso}">
                <div class="pr-type">Best Set Volume</div>
                <div class="pr-number">${fmtVol(data.pr.by_vol.volume)}</div>
                <div class="pr-sub">${data.pr.by_vol.weight} kg × ${data.pr.by_vol.reps} reps · ${data.pr.by_vol.date}</div>
            </a>
        </div>
    </div>` : ''}

        <!-- Session history -->
        <div class="panel" style="animation:fadeUp 0.4s ease both">
            <div class="panel-title">Session History</div>
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Top Weight</th>
                        <th>Top e1RM</th>
                        <th>Volume</th>
                        <th>Sets</th>
                    </tr>
                </thead>
                <tbody>
                    ${sessions.map(s => {
        const bestE1rm = s.sets.length ? Math.max(...s.sets.map(x => {
            const w = x.weight_kg || 0, r = x.reps || 0;
            return w <= 0 || r === 0 ? 0 : (r === 1 ? w : w * (1 + r / 30));
        })) : 0;
        const pills = s.sets.map(x => {
            const e1rm = x.weight_kg <= 0 || x.reps === 0 ? 0 :
                (x.reps === 1 ? x.weight_kg : x.weight_kg * (1 + x.reps / 30));
            const isBest = Math.abs(e1rm - bestE1rm) < 0.01 && bestE1rm > 0;
            const label = x.weight_kg > 0 ? `${x.weight_kg}×${x.reps}` : `BW×${x.reps}`;
            return `<span class="set-pill${isBest ? ' best' : ''}">${label}</span>`;
        }).join('');
        return `<tr>
                        <td><a href="/workout/${s.date}">${s.date_fmt}</a></td>
                        <td style="color:var(--text)">${s.top_weight > 0 ? s.top_weight + ' kg' : 'BW'}</td>
                        <td style="color:var(--blue)">${bestE1rm > 0 ? Math.round(bestE1rm * 10) / 10 + ' kg' : '—'}</td>
                        <td style="color:var(--label)">${fmtVol(s.volume)}</td>
                        <td><div class="sets-inline">${pills}</div></td>
                    </tr>`;
    }).join('')}
                </tbody>
            </table>
        </div>

    </div><!-- .main-col -->

    <div class="side-col">

        <!-- Next session -->
        ${data.prediction && data.prediction.exercise ? `
    <div style="animation:fadeUp 0.3s ease both">
        <div class="panel-title">Next Session</div>
        <div class="next-box">
            <div class="next-title">RECOMMENDATION</div>
            <div class="next-rec">
                ${data.prediction.is_bw ? 'BW' : data.prediction.rec_weight + ' kg'}
                × ${data.prediction.rec_reps} reps
            </div>
            <div class="next-note">${data.prediction.note}</div>
            ${(() => {
                const [label, cls] = STATUS_BADGE[data.prediction.status] || ['—', ''];
                return `<span class="badge ${cls}">${label}</span>`;
            })()}
            ${data.prediction.acwr > 0 ? `
            <div style="margin-top:10px;font-size:10px;color:var(--muted)">
                ACWR <span style="color:${data.prediction.acwr > 1.3 ? 'var(--red)' : 'var(--green)'}">
                ${data.prediction.acwr.toFixed(2)}</span>
            </div>` : ''}
            <div style="margin-top:4px;font-size:10px;color:var(--muted)">
                Last session ${data.prediction.days_since}d ago
            </div>
            ${data.prediction.best_e1rm > 0 ? `
            <div style="margin-top:4px;font-size:10px;color:var(--muted)">
                Best e1RM <span style="color:var(--blue)">${data.prediction.best_e1rm} kg</span>
            </div>` : ''}
        </div>
    </div>` : ''}

        <!-- Muscle map -->
        <div style="animation:fadeUp 0.35s ease both">
            <div class="panel-title">Muscles</div>
            <div class="muscle-map" id="muscleMap">
                <div style="color:var(--muted);font-size:10px">Loading...</div>
            </div>
            <div class="muscle-legend" id="muscleLegend" style="margin-top:16px"></div>
        </div>

    </div><!-- .side-col -->
</div><!-- .page-body -->
`;

    document.getElementById('app').innerHTML = html;

    // Charts
    if (data.exercise_type === 'timed') {
        renderDurationChart(data.duration_data, data.total_duration_data);
    } else if (data.exercise_type === 'bodyweight') {
        renderRepsChart(data.reps_data);
        renderVolChart(data.volume);  // sets×reps still useful
    } else {
        renderE1rmChart(data.e1rm);
        renderVolChart(data.volume);
    }

    renderMuscleMap(data.muscle_raw, data.secondary_raws || [], data.secondary_weights || {}, data.template_id || '');
}

function accentColor() {
    return document.documentElement.classList.contains('light') ? '#00843d' : '#00ff87';
}
function accentBg() {
    return document.documentElement.classList.contains('light') ? 'rgba(0,132,61,0.1)' : 'rgba(0,255,135,0.05)';
}

function renderE1rmChart(e1rm) {
    if (!e1rm || !e1rm.dates.length) return;
    const ctx = document.getElementById('e1rmChart');
    if (!ctx) return;
    if (e1rmChart) e1rmChart.destroy();

    e1rmChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: e1rm.dates,
            datasets: [{
                data: e1rm.values,
                borderColor: accentColor(),
                backgroundColor: accentBg(),
                borderWidth: 2,
                pointRadius: 3,
                pointBackgroundColor: accentColor(),
                pointHoverRadius: 5,
                tension: 0.3,
                fill: true,
            }]
        },
        options: {
            ...chartDefaults(),
            scales: {
                ...chartDefaults().scales,
                y: { ...chartDefaults().scales.y, ticks: { ...chartDefaults().scales.y.ticks, callback: v => (Math.round(v * 10) / 10) + ' kg' } },
            },
            plugins: {
                ...chartDefaults().plugins,
                tooltip: {
                    ...chartDefaults().plugins.tooltip, callbacks: {
                        label: ctx => `e1RM: ${ctx.parsed.y} kg`
                    }
                },
            }
        }
    });
}

function renderDurationChart(durationData) {
    if (!durationData || !durationData.dates.length) return;
    const ctx = document.getElementById('e1rmChart');
    if (!ctx) return;
    if (e1rmChart) e1rmChart.destroy();

    function fmtSecs(s) {
        const m = Math.floor(s / 60);
        const sec = s % 60;
        return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
    }

    e1rmChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: durationData.dates,
            datasets: [
                {
                    label: 'Max set',
                    data: durationData.max_values,
                    borderColor: accentColor(),
                    backgroundColor: accentBg(),
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: accentColor(),
                    tension: 0.3,
                    fill: true,
                },
                {
                    label: 'Total',
                    data: durationData.total_values,
                    borderColor: '#4da6ff',
                    backgroundColor: accentBg(),
                    borderWidth: 1.5,
                    pointRadius: 2,
                    pointBackgroundColor: '#4da6ff',
                    borderDash: [4, 3],
                    tension: 0.3,
                    fill: false,
                }
            ]
        },
        options: {
            ...chartDefaults(),
            scales: {
                ...chartDefaults().scales,
                y: {
                    ...chartDefaults().scales.y,
                    beginAtZero: true,
                    ticks: {
                        ...chartDefaults().scales.y.ticks,
                        callback: v => fmtSecs(v),
                    }
                }
            },
            plugins: {
                ...chartDefaults().plugins,
                legend: {
                    display: true, labels: {
                        color: document.documentElement.classList.contains('light') ? '#4a5568' : '#8899aa'
                        , font: { family: "'JetBrains Mono', monospace", size: 10 }
                    }
                },
                tooltip: {
                    ...chartDefaults().plugins.tooltip,
                    callbacks: { label: ctx => `${ctx.dataset.label}: ${fmtSecs(ctx.parsed.y)}` }
                },
            }
        }
    });
}

function renderRepsChart(repsData) {
    if (!repsData || !repsData.dates.length) return;
    const ctx = document.getElementById('e1rmChart');
    if (!ctx) return;
    if (e1rmChart) e1rmChart.destroy();

    e1rmChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: repsData.dates,
            datasets: [
                {
                    label: 'Max set',
                    data: repsData.max_values,
                    borderColor: accentColor(),
                    backgroundColor: accentBg(),
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: accentColor(),
                    pointHoverRadius: 5,
                    tension: 0.3,
                    fill: true,
                },
                {
                    label: 'Total',
                    data: repsData.total_values,
                    borderColor: '#4da6ff',
                    backgroundColor: accentBg(),
                    borderWidth: 1.5,
                    pointRadius: 2,
                    pointBackgroundColor: '#4da6ff',
                    borderDash: [4, 3],
                    tension: 0.3,
                    fill: false,
                }
            ]
        },
        options: {
            ...chartDefaults(),
            scales: {
                ...chartDefaults().scales,
                y: {
                    ...chartDefaults().scales.y,
                    beginAtZero: true,
                    ticks: {
                        ...chartDefaults().scales.y.ticks,
                        callback: v => `${v} reps`,
                        stepSize: 1,
                    }
                }
            },
            plugins: {
                ...chartDefaults().plugins,
                legend: {
                    display: true, labels: {
                        color: document.documentElement.classList.contains('light') ? '#4a5568' : '#8899aa'
                        , font: { family: "'JetBrains Mono', monospace", size: 10 }
                    }
                },
                tooltip: {
                    ...chartDefaults().plugins.tooltip,
                    callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} reps` }
                },
            }
        }
    });
}

function renderVolChart(vol) {
    if (!vol || !vol.weeks.length) return;
    const ctx = document.getElementById('volChart');
    const isLight = document.documentElement.classList.contains('light');
    if (!ctx) return;
    if (volChart) volChart.destroy();

    volChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: vol.weeks,
            datasets: [{
                data: vol.values,
                backgroundColor: isLight ? 'rgba(26,111,212,0.15)' : 'rgba(77,166,255,0.25)',
                borderColor: isLight ? '#1a6fd4' : '#4da6ff',
                borderWidth: 1,
                borderRadius: 2,
            }]
        },
        options: {
            ...chartDefaults(),
            scales: {
                ...chartDefaults().scales,
                y: { ...chartDefaults().scales.y, beginAtZero: true, ticks: { ...chartDefaults().scales.y.ticks, callback: v => v >= 1000 ? (v / 1000).toFixed(1) + 't' : v + 'kg' } },
            },
            plugins: {
                ...chartDefaults().plugins,
                tooltip: {
                    ...chartDefaults().plugins.tooltip, callbacks: {
                        label: ctx => `Volume: ${fmtVol(ctx.parsed.y)}`
                    }
                },
            }
        }
    });
}

function renderMuscleMap(primaryRaw, secondaryRaws, secondaryWeights, templateId) {
    // Build a volMap with primary at 1.0 and secondaries at their fraction
    _primaryRaw = primaryRaw;
    _normPrimary = MUSCLE_NORMALISE[primaryRaw] || primaryRaw;
    _muscleVolMap = {};

    if (_normPrimary) {
        _muscleVolMap[_normPrimary] = 1.0;
        if (primaryRaw === 'upper_back') {
            _muscleVolMap['traps'] = 1.0;
            _muscleVolMap['rhomboids'] = 1.0;
        }
    }

    secondaryRaws.forEach(sec => {
        const norm = MUSCLE_NORMALISE[sec] || sec;
        if (!norm) return;
        const frac = secondaryWeights[`${templateId}|${sec}`] ?? 0.5;
        _muscleVolMap[norm] = Math.max(_muscleVolMap[norm] || 0, frac);
        if (sec === 'upper_back') {
            _muscleVolMap['traps'] = Math.max(_muscleVolMap['traps'] || 0, frac);
            _muscleVolMap['rhomboids'] = Math.max(_muscleVolMap['rhomboids'] || 0, frac);
        }
    });

    if (!Object.keys(_muscleVolMap).length) {
        document.getElementById('muscleMap').innerHTML = '<div style="color:var(--muted);font-size:10px">No muscle data</div>';
        return;
    }

    fetch('/static/muscles.svg')
        .then(r => r.text())
        .then(svgText => {
            const parser = new DOMParser();
            const frontDoc = parser.parseFromString(svgText, 'image/svg+xml');
            const backDoc = parser.parseFromString(svgText, 'image/svg+xml');
            const frontSvg = frontDoc.querySelector('svg');
            const backSvg = backDoc.querySelector('svg');

            const fg = frontSvg.querySelectorAll('svg > g');
            const bg = backSvg.querySelectorAll('svg > g');
            if (fg.length >= 2) fg[0].remove();
            if (bg.length >= 2) bg[1].remove();

            frontSvg.setAttribute('viewBox', '0 0 507 1028');
            backSvg.setAttribute('viewBox', '508 0 507 1028');

            applyHeat(frontSvg, FRONT_MAP);
            applyHeat(backSvg, BACK_MAP);

            const mapEl = document.getElementById('muscleMap');
            mapEl.innerHTML = '';

            window._frontSvg = document.adoptNode(frontSvg);
            window._backSvg = document.adoptNode(backSvg);

            const frontCol = document.createElement('div');
            frontCol.className = 'muscle-map-col';
            frontCol.innerHTML = '<span>FRONT</span>';
            frontCol.appendChild(window._frontSvg);

            const backCol = document.createElement('div');
            backCol.className = 'muscle-map-col';
            backCol.innerHTML = '<span>BACK</span>';
            backCol.appendChild(window._backSvg);

            mapEl.appendChild(frontCol);
            mapEl.appendChild(backCol);

            // Legend
            const legendEl = document.getElementById('muscleLegend');
            const allMuscles = [
                [_normPrimary, 'primary'],
                ...secondaryRaws.map(s => [MUSCLE_NORMALISE[s] || s, 'secondary']),
            ].filter(([m]) => m);

            // Deduplicate
            const seen = new Set();
            const unique = allMuscles.filter(([m]) => { if (seen.has(m)) return false; seen.add(m); return true; });

            legendEl.innerHTML = unique.map(([m, type]) => {
                const isPrimary = type === 'primary';
                const color = heatColor(m, isPrimary);
                return `<div class="muscle-legend-row">
    <div class="muscle-dot" style="background:${color}"></div>
    <span class="muscle-legend-name">${m}</span>
    <span class="muscle-legend-type">${isPrimary ? 'primary' : 'secondary'}</span>
</div>`;
            }).join('');
        })
        .catch(() => {
            document.getElementById('muscleMap').innerHTML = '<div style="color:var(--muted);font-size:10px">SVG unavailable</div>';
        });
}

load();

function toggleTheme() {
    const isLight = document.documentElement.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    document.getElementById('btnTheme').textContent = isLight ? '☀' : '☾';
    if (e1rmChart) { e1rmChart.destroy(); e1rmChart = null; }
    if (volChart) { volChart.destroy(); volChart = null; }
    if (window._frontSvg) applyHeat(window._frontSvg, FRONT_MAP);
    if (window._backSvg) applyHeat(window._backSvg, BACK_MAP);
    if (window._exerciseData) {
        const d = window._exerciseData;
        if (d.exercise_type === 'timed') renderDurationChart(d.duration_data);
        else if (d.exercise_type === 'bodyweight') renderRepsChart(d.reps_data);
        else renderE1rmChart(d.e1rm);
        renderVolChart(d.volume);
    }
}


if (localStorage.getItem('theme') === 'light') {
    document.documentElement.classList.add('light');
    document.getElementById('btnTheme').textContent = '☀';
}

