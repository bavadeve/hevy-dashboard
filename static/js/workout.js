async function load() {
    try {
        const params = window.location.search;   // preserves ?range=week
        const res = await fetch(`/api/workout/${DATE}${params}`); const data = await res.json();
        if (data.error) throw new Error(data.error);
        render(data);
    } catch (e) {
        document.getElementById('app').innerHTML =
            `<div class="loading" style="color:var(--red)">ERROR: ${e.message}</div>`;
    }
}

function fmt(date) {
    return new Date(date).toLocaleDateString('en-GB', {
        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
    });
}

function fmtTime(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function setTypeBadge(type) {
    if (type === 'warmup') return '<span class="type-warmup">WARMUP</span>';
    if (type === 'failure') return '<span class="type-failure">FAILURE</span>';
    if (type === 'drop_set' || type === 'dropset') return '<span class="type-dropset">DROP</span>';
    return '';
}

function buildWorkoutBody(w, wi) {
    const totalSets = w.exercises.reduce((a, ex) => a + ex.sets.length, 0);
    const volDisplay = w.total_volume >= 1000
        ? `${(w.total_volume / 1000).toFixed(2)}t`
        : `${w.total_volume}kg`;

    let html = `
<div class="summary-bar">
    <div class="sum-stat"><div class="sum-value">${w.duration_min ?? '—'}</div><div class="sum-label">Minutes</div></div>
    <div class="sum-stat"><div class="sum-value">${w.exercises.length}</div><div class="sum-label">Exercises</div></div>
    <div class="sum-stat"><div class="sum-value">${totalSets}</div><div class="sum-label">Sets</div></div>
    <div class="sum-stat"><div class="sum-value">${volDisplay}</div><div class="sum-label">Volume</div></div>
</div>
<div class="exercises">`;

    w.exercises.forEach((ex, ei) => {
        const workSets = ex.sets.filter(s => s.type === 'normal');
        const bestE1rm = Math.max(...workSets.map(s => s.e1rm), 0);
        const bestIdx = ex.sets.findIndex(s => s.e1rm === bestE1rm && s.type === 'normal');

        html += `
    <div class="ex-card" style="animation-delay:${ei * 0.04}s">
        <div class="ex-header">
            <a class="ex-name" href="/exercise/${encodeURIComponent(ex.name)}" style="text-decoration:none">${ex.name}</a>
            ${ex.muscle ? `<span class="muscle-tag">${ex.muscle}</span>` : ''}
            <span class="ex-vol">${ex.volume > 0 ? ex.volume.toLocaleString() + ' kg total' : ''}</span>
        </div>
        ${ex.notes ? `<div class="ex-notes">"${ex.notes}"</div>` : ''}
        <table class="sets-table">
            <thead>
                <tr><th>#</th><th>Weight</th><th>Reps</th><th>Volume</th><th>e1RM</th><th>RPE</th><th>Type</th></tr>
            </thead>
            <tbody>
                ${ex.sets.map((s, si) => `
    <tr class="${si === bestIdx ? 'best-set' : ''}">
        <td class="set-num">${si + 1}</td>
        <td class="set-wt">${s.weight_kg > 0 ? s.weight_kg + ' kg' : 'BW'}${s.pr_weight ? '<span class="pr-badge pr-badge-wt">PR WT</span>' : ''}</td>
        <td class="set-reps">${s.reps}</td>
        <td class="set-vol">${s.volume > 0 ? s.volume + ' kg' : '—'}${s.pr_vol ? '<span class="pr-badge pr-badge-vol">PR VOL</span>' : ''}</td>
        <td class="set-e1rm">${s.e1rm > 0 ? s.e1rm + ' kg' : '—'}${s.pr_e1rm ? '<span class="pr-badge pr-badge-e1rm">PR 1RM</span>' : ''}</td>
        <td class="set-rpe">${s.rpe != null ? s.rpe : '—'}</td>
        <td>${setTypeBadge(s.type)}</td>
    </tr>`).join('')}
            </tbody>
        </table>
    </div>`;
    });

    html += `</div>`; // .exercises
    return html;
}

function render(data) {
    const workouts = data.workouts;
    const multiple = workouts.length > 1;

    const firstDate = workouts[0].start_time;
    document.getElementById('pageTitle').textContent =
        multiple ? `${workouts.length} WORKOUTS` : workouts[0].title.toUpperCase();
    document.getElementById('headerMeta').innerHTML = fmt(firstDate);

    let html = '';

    if (multiple) {
        workouts.forEach((w, wi) => {
            const isFirst = wi === 0;
            html += `
<div class="workout-block${isFirst ? ' open' : ''}" data-index="${wi}">
    <div class="workout-block-header" onclick="toggleWorkout(${wi})">
        <span class="workout-block-title">${w.title.toUpperCase()}</span>
        <span class="workout-block-time">${fmtTime(w.start_time)} – ${fmtTime(w.end_time)}</span>
        <span class="workout-block-chevron">${isFirst ? '▲' : '▼'}</span>
    </div>
    <div class="workout-block-body"${isFirst ? '' : ' style="display:none"'}>
        ${buildWorkoutBody(w, wi)}
    </div>
</div>`;
        });
    } else {
        html = buildWorkoutBody(workouts[0], 0);
    }

    let prefix = '';
    if (multiple) {
        const totalDuration = workouts.reduce((a, w) => a + (w.duration_min ?? 0), 0);
        const totalExercises = workouts.reduce((a, w) => a + w.exercises.length, 0);
        const totalSets = workouts.reduce((a, w) => a + w.exercises.reduce((b, ex) => b + ex.sets.length, 0), 0);
        const totalVolume = workouts.reduce((a, w) => a + w.total_volume, 0);
        const volDisplay = totalVolume >= 1000 ? `${(totalVolume / 1000).toFixed(2)}t` : `${totalVolume}kg`;
        prefix = `
<div class="summary-bar">
    <div class="sum-stat"><div class="sum-value">${totalDuration}</div><div class="sum-label">Minutes</div></div>
    <div class="sum-stat"><div class="sum-value">${totalExercises}</div><div class="sum-label">Exercises</div></div>
    <div class="sum-stat"><div class="sum-value">${totalSets}</div><div class="sum-label">Sets</div></div>
    <div class="sum-stat"><div class="sum-value">${volDisplay}</div><div class="sum-label">Volume</div></div>
</div>`;
    }

    document.getElementById('app').innerHTML = `${prefix}<div id="workout-list">${html}</div>`;
    renderSessionHeatmap(data.workouts, data.secondary_weights);
}

const FRONT_MAP = {
    'st5': 'shoulders',
    'st6': 'abdominals',
    'st10': 'biceps',
    'st11': 'chest',
    'st-forearms': 'forearms',
    'st12': 'quadriceps',   // adductors — closest match
    'st14': 'quadriceps',
    'st15': 'calves',
};

const BACK_MAP = {
    'st5': 'shoulders',    // rear delts
    'st6': 'traps',   // obliques
    'st9': 'lats',
    'st10': 'triceps',
    'st12': 'hamstrings',
    'st15': 'calves',
    'st4': 'glutes',
    'st-forearms': 'forearms',
    'st-rhomboids': 'rhomboids',
};

// Non-muscle structural classes — render as dark body color
const BODY_CLASSES = ['st2', 'st3', 'st7', 'st8', 'st0', 'st1'];

// Normalise raw Hevy muscle key → display name (same as backend MUSCLE_NORMALISE)
const MUSCLE_NORMALISE = {
    'chest': 'Chest', 'upper_chest': 'Chest', 'lower_chest': 'Chest',
    'quadriceps': 'Legs', 'hamstrings': 'Legs', 'glutes': 'Legs',
    'adductors': 'Legs', 'abductors': 'Legs', 'hip_flexors': 'Legs',
    'calves': 'Calves', 'lats': 'Back', 'upper_back': 'Traps',
    'lower_back': 'Back', 'traps': 'Traps', 'rhomboids': 'Traps',
    'shoulders': 'Shoulders', 'front_delts': 'Shoulders',
    'side_delts': 'Shoulders', 'rear_delts': 'Shoulders',
    'biceps': 'Biceps', 'triceps': 'Triceps', 'forearms': 'Forearms',
    'abs': 'Core', 'obliques': 'Core', 'core': 'Core',
};

const wkHeatmap = {
    frontSvg: null,
    backSvg: null,
    volMap: {},
    maxVol: 1,
};

function wkHeatColor(key) {
    const vol = wkHeatmap.volMap[key] || 0;
    const t = Math.pow(vol / wkHeatmap.maxVol, 0.5);
    const isLight = document.documentElement.classList.contains('light');
    if (t === 0) return isLight ? '#dde6f0' : '#1a2233';
    if (isLight) {
        const r = Math.round(255 + t * (0 - 255));
        const g = Math.round(255 + t * (168 - 255));
        const b = Math.round(255 + t * (85 - 255));
        return `rgb(${r},${g},${b})`;
    }
    const r = Math.round(26 + t * (0 - 26));
    const g = Math.round(34 + t * (255 - 34));
    const b = Math.round(51 + t * (135 - 51));
    return `rgb(${r},${g},${b})`;
}

function wkHeatOpacity(key) {
    return Math.max(0.2, Math.pow((wkHeatmap.volMap[key] || 0) / wkHeatmap.maxVol, 0.5));
}

function wkFmtVol(key) {
    const v = wkHeatmap.volMap[key] || 0;
    return v >= 1000 ? `${(v / 1000).toFixed(1)}t` : `${Math.round(v)}kg`;
}

function wkApplyHeat(svg, classMap) {
    const isLight = document.documentElement.classList.contains('light');
    const muscleElements = {};
    Object.entries(classMap).forEach(([cls, key]) => {
        svg.querySelectorAll(`.${cls}`).forEach(el => {
            el.style.fill = wkHeatColor(key);
            el.style.opacity = wkHeatOpacity(key);
            el.style.transition = 'transform 0.15s ease, opacity 0.15s ease';
            el.setAttribute('data-muscle', key);
            el.setAttribute('data-vol', wkFmtVol(key));
            if (!muscleElements[key]) muscleElements[key] = [];
            muscleElements[key].push(el);
        });
    });

    Object.entries(muscleElements).forEach(([key, els]) => {
        function getCenter() {
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            els.forEach(el => {
                try {
                    const b = el.getBBox();
                    minX = Math.min(minX, b.x); minY = Math.min(minY, b.y);
                    maxX = Math.max(maxX, b.x + b.width); maxY = Math.max(maxY, b.y + b.height);
                } catch (_) { }
            });
            return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
        }
        els.forEach(el => {
            el.addEventListener('mouseenter', e => {
                const { cx, cy } = getCenter();
                els.forEach(e2 => {
                    e2.style.transformOrigin = `${cx}px ${cy}px`;
                    e2.style.transform = 'scale(1.08)';
                    e2.style.opacity = '1';
                });
                const t = document.getElementById('wkTooltip');
                t.innerHTML = `<span style="color:var(--green)">${key}</span> · ${wkFmtVol(key)}`;
                t.style.display = 'block';
                const pw = t.offsetWidth;
                t.style.left = (e.clientX + 12 + pw > window.innerWidth) ? (e.pageX - pw - 12) + 'px' : (e.pageX + 12) + 'px';
                t.style.top = (e.pageY - 10) + 'px';
            });
            el.addEventListener('mouseleave', () => {
                els.forEach(e2 => { e2.style.transform = 'scale(1)'; e2.style.opacity = wkHeatOpacity(key); });
                document.getElementById('wkTooltip').style.display = 'none';
            });
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

function renderSessionHeatmap(workouts, secondaryWeights) {
    wkHeatmap.volMap = {};

    workouts.forEach(w => {
        w.exercises.forEach(ex => {
            const key = ex.muscle_raw;
            if (!key || key === 'other') return;
            const exVol = ex.sets
                .filter(s => s.type === 'normal')
                .reduce((a, s) => a + s.volume, 0);

            wkHeatmap.volMap[key] = (wkHeatmap.volMap[key] || 0) + exVol;
            if (key === 'upper_back') {
                wkHeatmap.volMap['traps'] = (wkHeatmap.volMap['traps'] || 0) + exVol;
                wkHeatmap.volMap['rhomboids'] = (wkHeatmap.volMap['rhomboids'] || 0) + exVol;
            }

            (ex.secondary_raws || []).forEach(sec => {
                if (!sec || sec === 'other') return;
                const frac = secondaryWeights[`${ex.template_id}|${sec}`] ?? 0.5;
                wkHeatmap.volMap[sec] = (wkHeatmap.volMap[sec] || 0) + exVol * frac;
                if (sec === 'upper_back') {
                    wkHeatmap.volMap['traps'] = (wkHeatmap.volMap['traps'] || 0) + exVol * frac;
                    wkHeatmap.volMap['rhomboids'] = (wkHeatmap.volMap['rhomboids'] || 0) + exVol * frac;
                }
            });
        });
    });

    if (!Object.keys(wkHeatmap.volMap).length) return;

    wkHeatmap.maxVol = Math.max(...Object.values(wkHeatmap.volMap), 1);

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
            frontSvg.style.cssText = 'width:100%;max-width:160px';
            backSvg.style.cssText = 'width:100%;max-width:160px';

            wkApplyHeat(frontSvg, FRONT_MAP);
            wkApplyHeat(backSvg, BACK_MAP);

            wkHeatmap.frontSvg = document.adoptNode(frontSvg);
            wkHeatmap.backSvg = document.adoptNode(backSvg);

            const legend = Object.entries(wkHeatmap.volMap)
                .sort((a, b) => b[1] - a[1])
                .map(([m, v]) => {
                    const fmt = v >= 1000 ? `${(v / 1000).toFixed(1)}t` : `${Math.round(v)}kg`;
                    return `<div style="display:flex;align-items:center;gap:8px">
    <div style="width:10px;height:10px;background:${wkHeatColor(m)};flex-shrink:0;border-radius:2px"></div>
    <span style="color:var(--label)">${m}</span>
    <span style="color:var(--text);margin-left:auto">${fmt}</span>
</div>`;
                }).join('');

            const frontCol = document.createElement('div');
            frontCol.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:6px';
            frontCol.innerHTML = '<span style="font-size:9px;letter-spacing:3px;color:var(--muted)">FRONT</span>';
            frontCol.appendChild(wkHeatmap.frontSvg);

            const backCol = document.createElement('div');
            backCol.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:6px';
            backCol.innerHTML = '<span style="font-size:9px;letter-spacing:3px;color:var(--muted)">BACK</span>';
            backCol.appendChild(wkHeatmap.backSvg);

            const legendCol = document.createElement('div');
            legendCol.className = 'heatmap-legend-small';
            legendCol.innerHTML = `<div style="font-size:9px;letter-spacing:3px;color:var(--muted);margin-bottom:4px">SESSION VOLUME</div>${legend}`;

            const svgRow = document.createElement('div');
            svgRow.style.cssText = 'display:flex;gap:8px;justify-content:center';
            svgRow.appendChild(frontCol);
            svgRow.appendChild(backCol);

            const container = document.createElement('div');
            container.className = 'session-heatmap';
            container.style.cssText = 'display:flex;flex-direction:column;gap:16px';
            container.appendChild(svgRow);
            container.appendChild(legendCol);

            const app = document.getElementById('app');
            const workoutList = document.getElementById('workout-list');
            if (workoutList) {
                const wrapper = document.createElement('div');
                wrapper.style.cssText = 'display:flex;align-items:flex-start;width:fit-content';

                workoutList.style.width = '1100px';
                container.style.cssText = 'flex-shrink:0;padding:24px 24px 0 16px';

                app.removeChild(workoutList);
                wrapper.appendChild(workoutList);
                wrapper.appendChild(container);
                app.appendChild(wrapper);
            } else {
                app.appendChild(container);
            }
        })
        .catch(() => { });
}

function toggleWorkout(index) {
    document.querySelectorAll('.workout-block').forEach((block, i) => {
        const body = block.querySelector('.workout-block-body');
        const chevron = block.querySelector('.workout-block-chevron');
        const open = i === index && !block.classList.contains('open');
        block.classList.toggle('open', open);
        body.style.display = open ? '' : 'none';
        if (chevron) chevron.textContent = open ? '▲' : '▼';
    });
}

function toggleTheme() {
    const isLight = document.documentElement.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    document.getElementById('btnTheme').textContent = isLight ? '☀' : '☾';
    if (wkHeatmap.frontSvg) wkApplyHeat(wkHeatmap.frontSvg, FRONT_MAP);
    if (wkHeatmap.backSvg) wkApplyHeat(wkHeatmap.backSvg, BACK_MAP);
}

if (localStorage.getItem('theme') === 'light') {
    document.documentElement.classList.add('light');
    document.getElementById('btnTheme').textContent = '☀';
}

load();
