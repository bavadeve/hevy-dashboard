function fmtMonth(str) {
    const [y, m] = str.split('-');
    return new Date(y, m - 1, 1).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' }).toUpperCase();
}

function fmtVol(v) {
    return v >= 1000 ? `${(v / 1000).toFixed(2)}t` : `${Math.round(v)}kg`;
}

function adjacentMonth(str, delta) {
    const [y, m] = str.split('-').map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

async function load() {
    try {
        const res = await fetch(`/api/month/${MONTH}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        render(data);
    } catch (e) {
        document.getElementById('app').innerHTML =
            `<div class="loading" style="color:var(--red)">ERROR: ${e.message}</div>`;
    }
}

function render(data) {
    const { summary, workout_list } = data;

    document.getElementById('pageTitle').textContent = fmtMonth(MONTH);
    document.getElementById('prevMonth').href = `/month/${adjacentMonth(MONTH, -1)}`;
    document.getElementById('nextMonth').href = `/month/${adjacentMonth(MONTH, +1)}`;

    const volDisplay = fmtVol(summary.volume);

    let html = `
<div class="summary-bar">
    <div class="sum-stat"><div class="sum-value">${summary.workouts}</div><div class="sum-label">Workouts</div></div>
    <div class="sum-stat"><div class="sum-value">${summary.duration_min}</div><div class="sum-label">Minutes</div></div>
    <div class="sum-stat"><div class="sum-value">${summary.sets}</div><div class="sum-label">Sets</div></div>
    <div class="sum-stat"><div class="sum-value">${volDisplay}</div><div class="sum-label">Volume</div></div>
</div>
<div class="main-col">
    <table class="workout-table">
        <thead>
            <tr><th>Date</th><th>Workout</th><th>Duration</th><th>Volume</th></tr>
        </thead>
        <tbody>
            ${workout_list.map(w => `
            <tr onclick="window.location='/workout/${w.date}'" style="cursor:pointer">
                <td class="wt-date">${new Date(w.date).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}</td>
                <td class="wt-title">${w.title}</td>
                <td class="wt-dur">${w.duration_min ?? '—'} min</td>
                <td class="wt-vol">${fmtVol(w.volume)}</td>
            </tr>`).join('')}
        </tbody>
    </table>
</div>`;

    document.getElementById('app').innerHTML = html;
    renderHeatmap(data);
}

// ── Heatmap ───────────────────────────────────────────────────────────────────

const FRONT_MAP = {
    'st5': 'shoulders', 'st6': 'abdominals', 'st10': 'biceps',
    'st11': 'chest', 'st-forearms': 'forearms', 'st12': 'quadriceps',
    'st14': 'quadriceps', 'st15': 'calves',
};
const BACK_MAP = {
    'st5': 'shoulders', 'st6': 'traps', 'st9': 'lats', 'st10': 'triceps',
    'st12': 'hamstrings', 'st15': 'calves', 'st4': 'glutes',
    'st-forearms': 'forearms', 'st-rhomboids': 'rhomboids',
};
const BODY_CLASSES = ['st2', 'st3', 'st7', 'st8', 'st0', 'st1'];

const heatmap = { volMap: {}, maxVol: 1, frontSvg: null, backSvg: null };

function heatColor(key) {
    const t = Math.pow((heatmap.volMap[key] || 0) / heatmap.maxVol, 0.5);
    const isLight = document.documentElement.classList.contains('light');
    if (t === 0) return isLight ? '#dde6f0' : '#1a2233';
    if (isLight) {
        return `rgb(${Math.round(255 + t * -255)},${Math.round(255 + t * (168 - 255))},${Math.round(255 + t * (85 - 255))})`;
    }
    return `rgb(${Math.round(26 + t * -26)},${Math.round(34 + t * 221)},${Math.round(51 + t * 84)})`;
}

function heatOpacity(key) {
    return Math.max(0.2, Math.pow((heatmap.volMap[key] || 0) / heatmap.maxVol, 0.5));
}

function applyHeat(svg, classMap) {
    const isLight = document.documentElement.classList.contains('light');
    const muscleEls = {};
    Object.entries(classMap).forEach(([cls, key]) => {
        svg.querySelectorAll(`.${cls}`).forEach(el => {
            el.style.fill = heatColor(key);
            el.style.opacity = heatOpacity(key);
            el.style.transition = 'transform 0.15s ease, opacity 0.15s ease';
            el.setAttribute('data-muscle', key);
            if (!muscleEls[key]) muscleEls[key] = [];
            muscleEls[key].push(el);
        });
    });

    Object.entries(muscleEls).forEach(([key, els]) => {
        els.forEach(el => {
            el.addEventListener('mouseenter', e => {
                els.forEach(e2 => { e2.style.transform = 'scale(1.08)'; e2.style.opacity = '1'; });
                const t = document.getElementById('monthTooltip');
                const vol = heatmap.volMap[key] || 0;
                t.innerHTML = `<span style="color:var(--green)">${key}</span> · ${fmtVol(vol)}`;
                t.style.display = 'block';
                const pw = t.offsetWidth;
                t.style.left = (e.clientX + 12 + pw > window.innerWidth ? e.pageX - pw - 12 : e.pageX + 12) + 'px';
                t.style.top = (e.pageY - 10) + 'px';
            });
            el.addEventListener('mouseleave', () => {
                els.forEach(e2 => { e2.style.transform = 'scale(1)'; e2.style.opacity = heatOpacity(key); });
                document.getElementById('monthTooltip').style.display = 'none';
            });
        });
    });

    BODY_CLASSES.forEach(cls => {
        svg.querySelectorAll(`.${cls}`).forEach(el => {
            el.style.fill = isLight ? '#c8d4e0' : '#1a2233';
            el.style.opacity = '1';
        });
    });
    svg.querySelectorAll('path,ellipse,rect,circle').forEach(el => {
        el.style.stroke = isLight ? '#7a8fa8' : '#0d1117';
        el.style.strokeWidth = '1.5px';
    });
    svg.querySelectorAll('.st13').forEach(el => el.remove());
}

function renderHeatmap(data) {
    heatmap.volMap = { ...data.muscle_volume };

    // Expand upper_back into traps + rhomboids
    if (heatmap.volMap['upper_back']) {
        const v = heatmap.volMap['upper_back'];
        heatmap.volMap['traps'] = (heatmap.volMap['traps'] || 0) + v;
        heatmap.volMap['rhomboids'] = (heatmap.volMap['rhomboids'] || 0) + v;
    }

    heatmap.maxVol = Math.max(...Object.values(heatmap.volMap), 1);

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

            heatmap.frontSvg = document.adoptNode(frontSvg);
            heatmap.backSvg = document.adoptNode(backSvg);

            const legend = Object.entries(heatmap.volMap)
                .sort((a, b) => b[1] - a[1])
                .map(([m, v]) => `
<div style="display:flex;align-items:center;gap:8px">
    <div style="width:10px;height:10px;background:${heatColor(m)};flex-shrink:0;border-radius:2px"></div>
    <span style="color:var(--label)">${m}</span>
    <span style="color:var(--text);margin-left:auto">${fmtVol(v)}</span>
</div>`).join('');

            const sideCol = document.createElement('div');
            sideCol.className = 'side-col';

            const svgRow = document.createElement('div');
            svgRow.style.cssText = 'display:flex;gap:8px;justify-content:center';

            const frontCol = document.createElement('div');
            frontCol.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:6px';
            frontCol.innerHTML = '<span style="font-size:9px;letter-spacing:3px;color:var(--muted)">FRONT</span>';
            frontCol.appendChild(heatmap.frontSvg);

            const backCol = document.createElement('div');
            backCol.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:6px';
            backCol.innerHTML = '<span style="font-size:9px;letter-spacing:3px;color:var(--muted)">BACK</span>';
            backCol.appendChild(heatmap.backSvg);

            svgRow.appendChild(frontCol);
            svgRow.appendChild(backCol);

            const legendDiv = document.createElement('div');
            legendDiv.className = 'heatmap-legend-small';
            legendDiv.innerHTML = `<div style="font-size:9px;letter-spacing:3px;color:var(--muted);margin-bottom:4px">MONTHLY VOLUME</div>${legend}`;

            sideCol.appendChild(svgRow);
            sideCol.appendChild(legendDiv);

            document.getElementById('app').appendChild(sideCol);
        })
        .catch(() => { });
}

function toggleTheme() {
    const isLight = document.documentElement.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    document.getElementById('btnTheme').textContent = isLight ? '☀' : '☾';
    if (heatmap.frontSvg) applyHeat(heatmap.frontSvg, FRONT_MAP);
    if (heatmap.backSvg) applyHeat(heatmap.backSvg, BACK_MAP);
}

if (localStorage.getItem('theme') === 'light') {
    document.documentElement.classList.add('light');
    document.getElementById('btnTheme').textContent = '☀';
}

load();