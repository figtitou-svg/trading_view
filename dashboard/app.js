// ═══════════════════════════════════════════════════════
//  Dashboard trading — Forex (paper trading multi-signaux)
//  Le trading crypto classique est arrêté (code archivé).
// ═══════════════════════════════════════════════════════

const API_BASE = '/api';

// ── Navigation entre pages ──────────────────────────────

const PAGES = ['forex', 'copytrading', 'settings'];
const FOREX_ROUTES = ['forex', 'bot', 'calendar', 'macro'];

// Route top-level dérivée du hash : #copytrading / tout le reste
// (dont les sous-routes forex #bot/..., #calendar, #macro) → forex.
function topPageFromHash() {
    const name = (location.hash || '').replace(/^#/, '').split('/')[0];
    if (name === 'copytrading' || name === 'settings') return name;
    return 'forex';
}

// Page actuellement affichée (mise à jour par showPage) — permet de détecter
// une navigation qui QUITTE la page Paramètres pour réinitialiser settingsDirty.
let currentPage = '';

function showPage(page) {
    if (currentPage === 'settings' && page !== 'settings') {
        // Quitter l'onglet Paramètres abandonne toute modification non enregistrée.
        settingsDirty = false;
    }
    currentPage = page;
    document.querySelectorAll('.nav-link').forEach(l =>
        l.classList.toggle('active', l.dataset.page === page));
    for (const p of PAGES) {
        document.getElementById(`page-${p}`).style.display = p === page ? '' : 'none';
    }
    if (page === 'copytrading') refreshCopytrading();
    else if (page === 'settings') refreshSettings();
    else routeForex();
}

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = link.dataset.page;
        if (page === 'forex') {
            // Conserver une éventuelle sous-route forex déjà présente.
            const current = (location.hash || '').replace(/^#/, '').split('/')[0];
            if (FOREX_ROUTES.includes(current)) {
                // Le hash ne va pas changer → pas de hashchange à attendre.
                showPage('forex');
            } else {
                location.hash = '#forex';   // déclenche hashchange → showPage une seule fois
            }
        } else {
            location.hash = '#' + page;   // hashchange → showPage
        }
    });
});

// ═══════════════════════════════════════════════════════
//  FOREX (paper trading multi-signaux)
// ═══════════════════════════════════════════════════════

// Bot affiché sur la page détail, dérivé de la route (#bot/<id>).
let selectedBot = '';

// ── Routeur des sous-pages Forex (hash URL → bouton retour utilisable) ──

function parseForexRoute() {
    const hash = (location.hash || '').replace(/^#/, '');
    const [name, arg] = hash.split('/');
    if (name === 'bot') {
        if (!arg) return { name: 'forex' };
        try {
            return { name: 'bot', botId: decodeURIComponent(arg) };
        } catch (_) {
            return { name: 'forex' };
        }
    }
    if (FOREX_ROUTES.includes(name)) return { name };
    return { name: 'forex' };
}

function routeForex() {
    const route = parseForexRoute();
    const sections = {
        forex: document.getElementById('forex-home'),
        bot: document.getElementById('forex-bot-detail'),
        calendar: document.getElementById('forex-calendar-page'),
        macro: document.getElementById('forex-macro-page'),
    };
    for (const key of Object.keys(sections)) {
        sections[key].style.display = key === route.name ? '' : 'none';
    }
    if (route.name === 'bot') {
        selectedBot = route.botId;
        refreshBotDetail();
    } else if (route.name === 'calendar') {
        refreshCalendarPage();
    } else if (route.name === 'macro') {
        refreshMacroPage();
    } else {
        refreshForexHome();
    }
}

function goToBot(botId) {
    location.hash = '#bot/' + encodeURIComponent(botId);
}

window.addEventListener('hashchange', () => showPage(topPageFromHash()));

// ── Barre générique : biais divergent (macro) ou simple 0→max (importance) ──

function renderBar({ diverging = false, value, max = 1, color }) {
    if (diverging) {
        const frac = Math.max(-1, Math.min(1, (value || 0) / max));
        const half = Math.abs(frac) * 50;
        const left = frac >= 0 ? 50 : 50 - half;
        const c = color || (frac >= 0 ? 'var(--accent-green)' : 'var(--accent-red)');
        return `<div class="bar-track">
            <div class="bar-fill" style="left:${left}%; width:${half}%; background:${c};"></div>
            <div class="bar-tick"></div>
        </div>`;
    }
    const pct = Math.max(0, Math.min(100, ((value || 0) / max) * 100));
    const c = color || 'var(--accent-yellow)';
    return `<div class="bar-track">
        <div class="bar-fill" style="left:0; width:${pct}%; background:${c};"></div>
    </div>`;
}

// ── Page d'accueil Forex ──

async function refreshForexHome() {
    try {
        const [btRes, pfRes, calRes, mcRes] = await Promise.all([
            fetch(API_BASE + '/forex/bots'),
            fetch(API_BASE + '/forex/portfolio'),
            fetch(API_BASE + '/forex/calendar?limit=12'),
            fetch(API_BASE + '/forex/macro'),
        ]);
        const botsIdx = btRes.ok ? await btRes.json() : { available: false, bots: [] };
        const pf = pfRes.ok ? await pfRes.json() : { available: false };
        const cal = calRes.ok ? await calRes.json() : [];
        const macro = mcRes.ok ? await mcRes.json() : { available: false };

        const badge = document.getElementById('forex-runner-status');
        if (!botsIdx.available) {
            badge.textContent = '⚪ Runner non démarré'; badge.className = 'watcher-badge';
        } else if (botsIdx.runner_active) {
            badge.textContent = '🟢 Runner actif'; badge.className = 'watcher-badge active';
        } else {
            badge.textContent = '🔴 Runner inactif'; badge.className = 'watcher-badge inactive';
        }

        if (pf.available && pf.equity != null) {
            const start = pf.start_equity || 0;
            const pnlEur = pf.equity - start;
            document.getElementById('forex-equity').textContent =
                pf.equity.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
            const pnlEl = document.getElementById('forex-pnl');
            pnlEl.textContent =
                `${pnlEur >= 0 ? '+' : ''}${pnlEur.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} € ` +
                `(${pf.return_pct >= 0 ? '+' : ''}${pf.return_pct}%)`;
            pnlEl.className = 'pnl-indicator ' + (pnlEur >= 0 ? 'positive' : 'negative');
            document.getElementById('forex-invested').textContent =
                `sur ${start.toLocaleString('fr-FR')} € investis`;
        }

        renderBotCards(botsIdx);
        renderCalendarWidget(cal);
        if (macro.available) renderMacroWidget(macro.biases || {});
    } catch (_) {}
}

function renderBotCards(idx) {
    const el = document.getElementById('forex-bots');
    if (!el) return;
    const bots = idx.bots || [];
    if (!bots.length) {
        el.innerHTML = '<p style="color:#8e8e93">En attente du runner forex...</p>';
        return;
    }
    const sorted = [...bots].sort((a, b) => (b.return_pct ?? 0) - (a.return_pct ?? 0));
    el.innerHTML = sorted.map(b => {
        const ret = b.return_pct ?? 0;
        const cls = ret > 0 ? 'positive' : (ret < 0 ? 'negative' : '');
        const open = (b.open_positions || []).length;
        return `<div class="bot-card" onclick="if (!event.target.closest('.bot-delete-btn')) goToBot('${b.bot}')" title="${b.label || ''}">
            <div class="bot-card-top">
                <strong>${b.bot}</strong>
                <span class="${cls}">${ret >= 0 ? '+' : ''}${ret.toFixed(2)} %</span>
            </div>
            <div class="bot-card-stats">
                <span>${(b.equity ?? 0).toLocaleString('fr-FR', {maximumFractionDigits: 0})} €</span>
                <span>${b.trades ?? 0} trades</span>
                <span>${b.trades ? (b.win_rate ?? 0) + ' % win' : '— win'}</span>
                <span>${open || 0} position${open === 1 ? '' : 's'}</span>
            </div>
            <button class="clear-blocked-btn bot-delete-btn" style="margin-top:10px;"
                    data-bot="${b.bot}">Supprimer</button>
        </div>`;
    }).join('');
}

function calendarRowHtml(e, { expandable = false, index = 0 } = {}) {
    const when = new Date(e.dt).toLocaleString('fr-FR', { weekday: 'short', hour: '2-digit', minute: '2-digit' });
    const bar = renderBar({ value: e.importance ?? 0, max: 5 });
    const head = `<div class="bar-row">
        <span>${e.currency} — ${e.title}</span>
        <span style="color:#8e8e93">${when}${e.forecast != null ? ' · prév. ' + e.forecast : ''}</span>
    </div>`;
    if (!expandable) {
        return `<div class="asset-item" style="flex-direction:column; align-items:stretch;">${head}${bar}</div>`;
    }
    const pairsTxt = (e.pairs || []).map(p => p.replace('_', '/')).join(', ') || 'aucune paire suivie';
    return `<div class="asset-item" style="flex-direction:column; align-items:stretch; cursor:pointer;" onclick="toggleCalendarDetail(${index})">
        ${head}${bar}
        <div id="cal-detail-${index}" style="display:none; margin-top:8px; font-size:12px; color:#c7c7cc;">
            <p>${e.explanation || ''}</p>
            <p style="margin-top:4px; color:#8e8e93;">Paires concernées : ${pairsTxt}</p>
        </div>
    </div>`;
}

function renderCalendarWidget(events) {
    const el = document.getElementById('forex-calendar-widget');
    if (!el) return;
    if (!events.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucune annonce à venir dans le cache.</p>';
        return;
    }
    el.innerHTML = events.slice(0, 3).map(e => calendarRowHtml(e)).join('');
}

function toggleCalendarDetail(i) {
    const el = document.getElementById('cal-detail-' + i);
    if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}

function macroBiasRowHtml(pair, bias, { rateInfo = null } = {}) {
    const label = bias > 0.1 ? 'Haussier' : bias < -0.1 ? 'Baissier' : 'Neutre';
    const cls = bias > 0.1 ? 'positive' : bias < -0.1 ? 'negative' : '';
    const detail = rateInfo
        ? `<p style="color:#8e8e93; font-size:11px; margin-top:6px;">${rateInfo}</p>` : '';
    return `<div class="asset-item" style="flex-direction:column; align-items:stretch;">
        <div class="bar-row">
            <span><strong>${pair.replace('_', '/')}</strong> <span class="${cls}">${label}</span></span>
            <span style="color:#8e8e93">${bias > 0 ? '+' : ''}${bias.toFixed(2)}</span>
        </div>
        ${renderBar({ diverging: true, value: bias })}
        ${detail}
    </div>`;
}

function renderMacroWidget(biases) {
    const el = document.getElementById('forex-macro-widget');
    if (!el) return;
    const pairs = Object.keys(biases || {});
    if (!pairs.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucune donnée macro disponible.</p>';
        return;
    }
    const top3 = pairs.sort((a, b) => Math.abs(biases[b]) - Math.abs(biases[a])).slice(0, 3);
    el.innerHTML = top3.map(p => macroBiasRowHtml(p, biases[p])).join('');
}

// ── Page détail d'un bot ──

const FX_STATUS = {
    entered: ['🟢 ENTRÉE', 'ok'],
    in_position: ['📈 EN POSITION', 'bought'],
    closed: ['✅ CLÔTURÉ', 'ok'],
    flat: ['⚪ Pas de signal', ''],
    risk_block: ['🛑 Risque', 'blocked'],
    lev_block: ['🛑 Levier', 'blocked'],
    combo_disabled: ['⛔ Combo désactivé', 'blocked'],
    no_data: ['⚠️ Pas de données', 'blocked'],
    warmup: ['⏳ Warmup', ''],
    '?': ['—', ''],
};

// Graphique en bougies avec axe des prix, niveaux (entrée/stop/TP ou sortie)
// affichés en clair. Fenêtre resserrée (~18 bougies) autour du dernier
// événement. Les bougies viennent du cache glissant (80 dernières, cf.
// forex/paper/runner.py::_CHART_CANDLES) : un trade plus ancien que cette
// fenêtre n'a plus son historique disponible, d'où le message de repli.
function candlestickChartSvg(candles, opts) {
    const { entryPrice, entryTs, stop, tp, exitPrice, exitTs, exitReason, direction, decimals = 5 } = opts;
    if (!candles || candles.length < 2) {
        return '<p style="color:#8e8e93; font-size:12px;">Graphique indisponible (données en cours de chargement).</p>';
    }
    const WINDOW = 18;
    // findIndex seul ne suffit pas : si entryTs est PLUS ANCIEN que toutes les
    // bougies en cache, toutes satisfont `c[0] >= entryTs` et il renverrait 0
    // (pas -1) — masquant le cas « trade sorti de la fenêtre de cache » que ce
    // garde-fou doit justement détecter. On le teste explicitement à part.
    const entryIdx = entryTs != null
        ? (entryTs < candles[0][0] ? -1 : candles.findIndex(c => c[0] >= entryTs))
        : -1;
    if (entryTs != null && entryIdx === -1) {
        return '<p style="color:#8e8e93; font-size:12px;">Graphique indisponible (historique hors de la fenêtre en cache).</p>';
    }
    const exitIdx = exitTs != null ? candles.findIndex(c => c[0] >= exitTs) : -1;
    const anchor = exitIdx >= 0 ? exitIdx : (entryIdx >= 0 ? entryIdx : candles.length - 1);

    let start, end;
    if (exitTs == null && entryIdx >= 0) {
        // Position encore ouverte : pas de fenêtre centrée fixe — on montre
        // tout depuis quelques bougies avant l'entrée jusqu'à la bougie la
        // plus récente (« maintenant »), quitte à afficher plus de bougies
        // qu'un trade clôturé classique.
        const LEAD_IN = 8;
        start = Math.max(0, entryIdx - LEAD_IN);
        end = candles.length;
    } else {
        const half = Math.floor(WINDOW / 2);
        start = Math.max(0, anchor - half);
        end = Math.min(candles.length, start + WINDOW);
        start = Math.max(0, end - WINDOW);
    }
    const win = candles.slice(start, end);
    if (win.length < 2) {
        return '<p style="color:#8e8e93; font-size:12px;">Graphique indisponible (pas assez de bougies).</p>';
    }

    const W = 340, H = 160, padL = 4, padR = 78, padY = 14;
    const plotW = W - padL - padR;
    const levels = [entryPrice, stop, tp, exitPrice].filter(v => v != null);
    const highs = win.map(c => c[2]), lows = win.map(c => c[3]);
    let lo = Math.min(...lows, ...levels);
    let hi = Math.max(...highs, ...levels);
    if (hi === lo) { hi += 1e-5; lo -= 1e-5; }
    const range = hi - lo;
    const n = win.length;
    const cw = plotW / n;
    const x = i => padL + i * cw + cw / 2;
    const y = v => padY + (1 - (v - lo) / range) * (H - 2 * padY);
    const f = v => v.toFixed(decimals);

    const bodies = win.map((c, i) => {
        const [, o, h, l, close] = c;
        const up = close >= o;
        const color = up ? 'var(--accent-green)' : 'var(--accent-red)';
        const bw = Math.max(2, cw * 0.6);
        const bodyTop = Math.min(y(o), y(close));
        const bodyH = Math.max(1, Math.abs(y(o) - y(close)));
        return `<line x1="${x(i)}" x2="${x(i)}" y1="${y(h)}" y2="${y(l)}" stroke="${color}" stroke-width="1"/>
                <rect x="${(x(i) - bw / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${bw.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${color}"/>`;
    }).join('');

    const hline = (v, color, label) => {
        if (v == null) return '';
        const yy = y(v);
        return `<line x1="${padL}" x2="${W - padR + 4}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${color}" stroke-width="1"
                      stroke-dasharray="4,3" opacity="0.9"/>
                <text x="${W - padR + 6}" y="${(yy + 3).toFixed(1)}" fill="${color}" font-size="9">${label} ${f(v)}</text>`;
    };

    const marker = (idx, price, color, label, above) => {
        if (idx == null || idx < 0 || price == null) return '';
        const cx = x(idx), cy = y(price);
        const ty = above ? cy - 8 : cy + 14;
        return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4" fill="#111" stroke="${color}" stroke-width="1.5"/>
                <text x="${Math.min(cx + 4, W - padR - 4).toFixed(1)}" y="${ty.toFixed(1)}" fill="#fff" font-size="9">${label}</text>`;
    };

    const relEntryIdx = entryIdx >= 0 ? entryIdx - start : -1;
    const relExitIdx = exitIdx >= 0 ? exitIdx - start : -1;
    const exitLabel = exitReason === 'stop-loss' ? 'SL' : exitReason === 'take-profit' ? 'TP' : (exitReason || '—');
    const exitColor = exitReason === 'stop-loss' ? 'var(--accent-red)' : 'var(--accent-green)';

    const firstDt = new Date(win[0][0]).toLocaleString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    const lastDt = new Date(win[win.length - 1][0]).toLocaleString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

    return `<div>
        <svg viewBox="0 0 ${W} ${H}" width="100%" height="160" style="background:#111; border-radius:8px;">
            <text x="2" y="12" fill="#666" font-size="9">${f(hi)}</text>
            <text x="2" y="${H - 4}" fill="#666" font-size="9">${f(lo)}</text>
            ${hline(tp, 'var(--accent-green)', 'TP')}
            ${hline(entryPrice, '#8e8e93', 'entrée')}
            ${hline(stop, 'var(--accent-red)', 'SL')}
            ${bodies}
            ${marker(relEntryIdx, entryPrice, '#fff', direction === 'long' ? '↑ entrée' : '↓ entrée', true)}
            ${exitPrice != null ? marker(relExitIdx, exitPrice, exitColor, `sortie (${exitLabel})`, false) : ''}
        </svg>
        <div style="display:flex; justify-content:space-between; font-size:10px; color:#888; margin-top:4px;">
            <span>${firstDt}</span><span>${lastDt}</span>
        </div>
    </div>`;
}

function renderForexSignals(pairs) {
    const el = document.getElementById('bot-signals');
    if (!pairs.length) {
        el.innerHTML = '<p style="color:#8e8e93">En attente du runner forex...</p>';
        return;
    }
    el.innerHTML = pairs.map(p => {
        const [label, cls] = FX_STATUS[p.status] || [p.status, ''];
        const price = p.price != null ? p.price : '--';
        const patternBadge = p.pattern ? `<span class="verdict-badge" style="margin-left:6px;">📐 ${p.pattern}</span>` : '';
        return `<div class="detection-item">
            <span class="verdict-badge ${cls}">${label}</span>${patternBadge}
            <div class="detection-main">
                <div class="detection-name">${p.pair.replace('_', '/')} <span style="color:#8e8e93">${price}</span></div>
                <div class="detection-meta">${p.detail || ''}</div>
            </div>
        </div>`;
    }).join('');
}

function renderBotPositions(positions, candlesByPair) {
    const el = document.getElementById('bot-positions');
    const keys = Object.keys(positions || {});
    if (!keys.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucune position ouverte.</p>';
        return;
    }
    const dec = k => k.endsWith('JPY') ? 3 : 5;
    const f = (v, k) => v == null ? '--' : Number(v).toFixed(dec(k));
    el.innerHTML = keys.map(k => {
        const p = positions[k];
        const dir = p.direction === 'long' ? '🟢 LONG' : '🔴 SHORT';
        const chart = candlestickChartSvg(candlesByPair[k] || [], {
            entryPrice: p.entry_price, entryTs: p.entry_ts, stop: p.stop, tp: p.tp,
            direction: p.direction, decimals: dec(k),
        });
        return `<div class="detection-item" style="flex-direction:column; align-items:stretch;">
            <div style="display:flex; align-items:center; gap:10px;">
                <span class="verdict-badge ${p.direction === 'long' ? 'ok' : 'blocked'}">${dir}</span>
                <div class="detection-main">
                    <div class="detection-name">${k.replace('_', '/')} @ ${f(p.entry_price, k)}</div>
                    <div class="detection-meta">stop ${f(p.stop, k)} · TP ${f(p.tp, k)}${p.risk_pct ? ' · risque ' + p.risk_pct + '%' : ''}</div>
                </div>
            </div>
            <div style="margin-top:8px;">${chart}</div>
        </div>`;
    }).join('');
}

function renderBotLastTrades(trades, candlesByPair) {
    const el = document.getElementById('bot-last-trades');
    if (!trades.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucun trade pour le moment.</p>';
        return;
    }
    const dec = k => k.endsWith('JPY') ? 3 : 5;
    el.innerHTML = trades.slice(0, 5).map(t => {
        const win = (t.pnl ?? 0) >= 0;
        const when = t.exit_ts ? new Date(t.exit_ts).toLocaleString('fr-FR') : '';
        const reasonLabel = t.exit_reason === 'stop-loss' ? 'SL' : t.exit_reason === 'take-profit' ? 'TP' : (t.exit_reason || '—');
        const chart = candlestickChartSvg(candlesByPair[t.pair] || [], {
            entryPrice: t.entry_price, entryTs: t.entry_ts,
            exitPrice: t.exit_price, exitTs: t.exit_ts, exitReason: t.exit_reason,
            direction: t.direction, decimals: dec(t.pair),
        });
        return `<div class="trade-item" style="flex-direction:column; align-items:stretch;">
            <div style="display:flex; justify-content:space-between;">
                <span class="trade-symbol">${t.pair.replace('_', '/')} ${t.direction === 'long' ? '↑' : '↓'}</span>
                <span class="${win ? 'positive' : 'negative'}">${win ? '+' : ''}${(t.pnl_pct ?? 0).toFixed(2)}% (${(t.pnl ?? 0).toFixed(2)} €) · ${reasonLabel}</span>
            </div>
            <span class="trade-time">${when}</span>
            <div style="margin-top:8px;">${chart}</div>
        </div>`;
    }).join('');
}

function renderBotLearning(learn) {
    const combosEl = document.getElementById('bot-combos');
    const learnedEl = document.getElementById('bot-learned');
    const clEl = document.getElementById('bot-changelog');
    const sumEl = document.getElementById('bot-learn-summary');
    if (!learn || !learn.available) {
        sumEl.textContent = '';
        return;
    }
    sumEl.textContent = `${learn.n_trades} trades analysés`;

    const combos = learn.combos || [];
    if (!combos.length) {
        combosEl.innerHTML = '<p style="color:#8e8e93">Pas encore de trade clôturé — le module apprend au fil des clôtures.</p>';
    } else {
        combosEl.innerHTML = combos.map(c => {
            const disabled = (learn.disabled_combos || []).includes(c.combo);
            const cls = c.verdict.includes('perdant') ? 'blocked' : c.verdict.includes('gagnant') ? 'ok' : '';
            const exp = (c.expectancy >= 0 ? '+' : '') + c.expectancy + '%';
            return `<div class="detection-item">
                <span class="verdict-badge ${cls}">${disabled ? '⛔ OFF' : c.n + ' trades'}</span>
                <div class="detection-main">
                    <div class="detection-name">${c.combo}</div>
                    <div class="detection-meta">n=${c.n} (${c.n_live ?? 0} live · ${c.n_backtest ?? 0} historique) · win ${c.win_rate}% · expectancy ${exp} · PF ${c.profit_factor ?? '∞'} · ${c.verdict}${c.enough_sample ? '' : ' (échantillon faible)'}</div>
                </div>
            </div>`;
        }).join('');
    }

    const params = learn.params || {};
    const pk = Object.keys(params);
    learnedEl.innerHTML = pk.length
        ? '⚙️ Paramètres appris : ' + pk.map(p => `${p.replace('_', '/')} → ${JSON.stringify(params[p])}`).join(' · ')
        : '⚙️ Paramètres : réglages par défaut (aucun ajustement appris pour l\'instant).';

    const cl = learn.changelog || [];
    if (!cl.length) {
        clEl.innerHTML = '<p style="color:#8e8e93">Aucun ajustement automatique pour l\'instant.</p>';
    } else {
        clEl.innerHTML = cl.map(e => {
            const when = e.ts ? new Date(e.ts).toLocaleString('fr-FR') : '';
            let txt;
            if (e.type === 'param') txt = `${(e.pair||'').replace('_','/')} ${e.field} : ${e.before ?? 'défaut'}→${e.after}`;
            else if (e.type === 'combo_disable') txt = `combo ${e.combo} désactivé`;
            else if (e.type === 'combo_enable') txt = `combo ${e.combo} réactivé`;
            else if (e.type === 'rollback') txt = `rollback (${e.reverted} annulé·s)`;
            else txt = e.type;
            return `<div class="detection-item">
                <span class="verdict-badge">${e.type === 'rollback' ? '↩️' : '🧠'}</span>
                <div class="detection-main">
                    <div class="detection-name">${txt}</div>
                    <div class="detection-meta">${when}${e.reason ? ' · ' + e.reason : ''}${e.sample ? ' · n=' + e.sample : ''}</div>
                </div>
            </div>`;
        }).join('');
    }
}

document.getElementById('bot-learn-toggle').addEventListener('click', () => {
    const d = document.getElementById('bot-learn-detail');
    d.style.display = d.style.display === 'none' ? '' : 'none';
});

async function refreshBotDetail() {
    if (!selectedBot) return;
    try {
        const q = '?bot=' + encodeURIComponent(selectedBot);
        const [stRes, pfRes, lrRes] = await Promise.all([
            fetch(API_BASE + '/forex/status' + q),
            fetch(API_BASE + '/forex/portfolio' + q),
            fetch(API_BASE + '/forex/learning' + q),
        ]);
        const status = stRes.ok ? await stRes.json() : { available: false };
        const pf = pfRes.ok ? await pfRes.json() : { available: false };
        const learn = lrRes.ok ? await lrRes.json() : { available: false };

        // Ne demande les bougies que des paires réellement affichées (positions
        // ouvertes + derniers trades) : évite de transférer tout le cache
        // (agrandi à ~300 bougies/paire) alors qu'un bot n'en utilise qu'une
        // poignée.
        const neededPairs = new Set([
            ...Object.keys(pf.open_positions || {}),
            ...(pf.trades || []).slice(0, 5).map(t => t.pair),
        ]);
        const candles = neededPairs.size
            ? await fetch(API_BASE + '/forex/candles?pair=' + encodeURIComponent([...neededPairs].join(',')))
                .then(r => r.ok ? r.json() : {})
            : {};

        const ret = (pf.available && pf.start_equity) ? pf.return_pct : null;
        document.getElementById('bot-detail-name').textContent =
            selectedBot + (ret != null ? ` (${ret >= 0 ? '+' : ''}${ret}%)` : '');
        document.getElementById('bot-detail-return').textContent = status.label || '';
        document.getElementById('bot-strategy-summary').textContent =
            status.description || 'Pas de description disponible pour ce bot.';

        renderForexSignals(status.pairs || []);
        renderBotPositions(pf.open_positions || {}, candles);
        renderBotLastTrades(pf.trades || [], candles);
        renderBotLearning(learn);
    } catch (_) {}
}

// ── Page Calendrier complète ──

function renderCalendarFull(events) {
    const el = document.getElementById('forex-calendar-full');
    if (!el) return;
    if (!events.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucune annonce à venir dans le cache.</p>';
        return;
    }
    el.innerHTML = events.map((e, i) => calendarRowHtml(e, { expandable: true, index: i })).join('');
}

async function refreshCalendarPage() {
    try {
        const res = await fetch(API_BASE + '/forex/calendar?limit=30');
        const events = res.ok ? await res.json() : [];
        renderCalendarFull(events);
    } catch (_) {}
}

// ── Page Macro complète ──

function renderMacroFull(details) {
    const el = document.getElementById('forex-macro-full');
    if (!el) return;
    if (!details.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucune donnée macro disponible.</p>';
        return;
    }
    const sorted = [...details].sort((a, b) => Math.abs(b.bias) - Math.abs(a.bias));
    el.innerHTML = sorted.map(d => {
        const rateInfo = (d.base_rate != null && d.quote_rate != null)
            ? `Taux ${d.base} ${d.base_rate.toFixed(2)}% vs ${d.quote} ${d.quote_rate.toFixed(2)}% (différentiel ${(d.base_rate - d.quote_rate).toFixed(2)} pt)`
            : 'Taux indisponibles pour cette paire.';
        return macroBiasRowHtml(d.pair, d.bias, { rateInfo });
    }).join('');
}

async function refreshMacroPage() {
    try {
        const res = await fetch(API_BASE + '/forex/macro');
        const macro = res.ok ? await res.json() : { available: false, details: [] };
        renderMacroFull(macro.details || []);
    } catch (_) {}
}

// ═══════════════════════════════════════════════════════
//  COPY TRADING (miroir Hyperliquid)
// ═══════════════════════════════════════════════════════

const shortAddr = a => a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '?';

const fmtEur2 = v => (v ?? 0).toLocaleString('fr-FR',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
const fmtRoi = v => `${v >= 0 ? '+' : ''}${((v ?? 0) * 100).toFixed(1)} %`;
const fmtUsdShort = v => (v ?? 0) >= 1e6
    ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round((v ?? 0) / 1000)}k`;

async function refreshCopytrading() {
    try {
        const [stRes, pfRes] = await Promise.all([
            fetch(API_BASE + '/copytrading/status'),
            fetch(API_BASE + '/copytrading/portfolio'),
        ]);
        const status = stRes.ok ? await stRes.json()
            : { available: false, candidates: [], follows: [] };
        const pf = pfRes.ok ? await pfRes.json()
            : { available: false, positions: [], trades: [] };

        const badge = document.getElementById('ct-runner-status');
        if (!status.available) {
            badge.textContent = '⚪ Runner non démarré'; badge.className = 'watcher-badge';
        } else if (status.runner_active) {
            badge.textContent = '🟢 Runner actif'; badge.className = 'watcher-badge active';
        } else {
            badge.textContent = '🔴 Runner inactif'; badge.className = 'watcher-badge inactive';
        }

        if (pf.available && pf.equity != null) {
            const start = pf.start_equity || 0;
            const pnl = pf.equity - start;
            document.getElementById('ct-equity').textContent = fmtEur2(pf.equity);
            const pnlEl = document.getElementById('ct-pnl');
            pnlEl.textContent = `${pnl >= 0 ? '+' : ''}${fmtEur2(pnl)} ` +
                `(${pf.return_pct >= 0 ? '+' : ''}${pf.return_pct}%)`;
            pnlEl.className = 'pnl-indicator ' + (pnl >= 0 ? 'positive' : 'negative');
            document.getElementById('ct-invested').textContent =
                `sur ${start.toLocaleString('fr-FR')} € virtuels`;
        }

        renderCtFollowed(status, pf);
        renderCtCandidates(status);
        renderCtPositions(pf.positions || []);
        renderCtTrades(pf.trades || []);
    } catch (_) {}
}

async function ctToggleFollow(address, follow) {
    try {
        const res = await fetch(
            `${API_BASE}/copytrading/${follow ? 'follow' : 'unfollow'}/${encodeURIComponent(address)}`,
            { method: 'POST' });
        if (res.ok) refreshCopytrading();
    } catch (_) {}
}

document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.ct-toggle-follow');
    if (!btn) return;
    btn.disabled = true;
    try {
        await ctToggleFollow(btn.dataset.address, btn.dataset.follow === 'true');
    } finally {
        btn.disabled = false;
    }
});

async function forexDeleteBot(botId) {
    const ok = confirm(
        `Supprimer définitivement le bot "${botId}" ?\n\n` +
        `Sa position ouverte (s'il y en a une) sera clôturée immédiatement. ` +
        `Il n'apparaîtra plus dans le classement, mais son historique reste archivé.`);
    if (!ok) return;
    try {
        const res = await fetch(`${API_BASE}/forex/bots/${encodeURIComponent(botId)}/disable`,
                                { method: 'POST' });
        if (res.ok) refreshForexHome();
    } catch (_) {}
}

document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.bot-delete-btn');
    if (!btn) return;
    btn.disabled = true;
    try {
        await forexDeleteBot(btn.dataset.bot);
    } finally {
        btn.disabled = false;
    }
});

function renderCtFollowed(status, pf) {
    const el = document.getElementById('ct-followed');
    const follows = status.follows || [];
    if (!follows.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucun trader copié — active « Copier » sur un candidat ci-dessous.</p>';
        return;
    }
    const byAddr = {};
    (status.candidates || []).forEach(c => { byAddr[c.address] = c; });
    const positions = pf.positions || [];
    el.innerHTML = follows.map(addr => {
        const c = byAddr[addr];
        const name = (c && c.display_name) || shortAddr(addr);
        const latent = positions.filter(p => p.trader === addr)
            .reduce((s, p) => s + (p.pnl_eur ?? 0), 0);
        const nPos = positions.filter(p => p.trader === addr).length;
        const stats = c
            ? `<span>compte ${fmtUsdShort(c.account_value)}</span>` +
              `<span>${fmtRoi(c.roi_week)} 7 j</span><span>${fmtRoi(c.roi_month)} 30 j</span>`
            : '<span>hors candidats actuels</span>';
        return `<div class="bot-card" title="${addr}">
            <div class="bot-card-top">
                <strong>${name}</strong>
                <span class="${latent >= 0 ? 'positive' : 'negative'}">${latent >= 0 ? '+' : ''}${latent.toFixed(2)} € latent</span>
            </div>
            <div class="bot-card-stats">${stats}<span>${nPos} position${nPos === 1 ? '' : 's'}</span></div>
            <button class="clear-blocked-btn ct-toggle-follow" style="margin-top:10px;"
                    data-address="${addr}" data-follow="false">Copier : ON — désactiver</button>
        </div>`;
    }).join('');
}

function renderCtCandidates(status) {
    const el = document.getElementById('ct-candidates');
    const cands = status.candidates || [];
    document.getElementById('ct-candidates-date').textContent =
        status.candidates_updated_at
            ? 'mis à jour ' + new Date(status.candidates_updated_at).toLocaleString('fr-FR')
            : '';
    if (!cands.length) {
        el.innerHTML = '<p style="color:#8e8e93">En attente du runner copy trading...</p>';
        return;
    }
    el.innerHTML = cands.map(c => {
        const name = c.display_name || shortAddr(c.address);
        const btn = c.followed
            ? `<button class="clear-blocked-btn ct-toggle-follow" data-address="${c.address}" data-follow="false">✓ Copié — désactiver</button>`
            : `<button class="clear-blocked-btn ct-toggle-follow" data-address="${c.address}" data-follow="true">Copier</button>`;
        return `<div class="detection-item">
            <span class="verdict-badge ${c.followed ? 'ok' : ''}">${c.followed ? '📋 COPIÉ' : '🏆'}</span>
            <div class="detection-main">
                <div class="detection-name">
                    <a href="https://app.hyperliquid.xyz/explorer/address/${c.address}" target="_blank" rel="noopener">${name}</a>
                </div>
                <div class="detection-meta">compte ${fmtUsdShort(c.account_value)} · ROI 30 j ${fmtRoi(c.roi_month)} · ROI 7 j ${fmtRoi(c.roi_week)}</div>
            </div>
            ${btn}
        </div>`;
    }).join('');
}

function renderCtPositions(positions) {
    const el = document.getElementById('ct-positions');
    if (!positions.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucune position miroir ouverte.</p>';
        return;
    }
    el.innerHTML = positions.map(p => {
        const dir = p.direction === 'long' ? '🟢 LONG' : '🔴 SHORT';
        const pnl = p.pnl_eur ?? 0;
        return `<div class="detection-item">
            <span class="verdict-badge ${p.direction === 'long' ? 'ok' : 'blocked'}">${dir}</span>
            <div class="detection-main">
                <div class="detection-name">${p.coin} · ${(p.size_eur ?? 0).toFixed(2)} €
                    <span class="${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} €</span>
                </div>
                <div class="detection-meta">entrée ${p.entry_price} · dernier ${p.last_price ?? '--'} · copié de ${shortAddr(p.trader)}</div>
            </div>
        </div>`;
    }).join('');
}

function renderCtTrades(trades) {
    const el = document.getElementById('ct-history');
    if (!trades.length) {
        el.innerHTML = '<p style="color:#8e8e93">Aucun trade clôturé pour le moment.</p>';
        return;
    }
    el.innerHTML = trades.map(t => {
        const win = (t.pnl_eur ?? 0) >= 0;
        const when = t.closed_at ? new Date(t.closed_at).toLocaleString('fr-FR') : '';
        return `<div class="trade-item">
            <div style="display:flex; justify-content:space-between; width:100%;">
                <span class="trade-symbol">${t.coin} ${t.direction === 'long' ? '↑' : '↓'}</span>
                <span class="${win ? 'positive' : 'negative'}">${win ? '+' : ''}${(t.pnl_eur ?? 0).toFixed(2)} €</span>
            </div>
            <span class="trade-time">${when} · ${t.reason || ''} · copié de ${shortAddr(t.trader)}</span>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
//  INITIALISATION
// ═══════════════════════════════════════════════════════

if (!location.hash) {
    location.hash = '#forex';   // déclenche hashchange → showPage une seule fois
} else {
    showPage(topPageFromHash());   // hash déjà présent, aucun event ne sera émis
}

// ═══════════════════════════════════════════════════════
//  PARAMÈTRES (notifications)
// ═══════════════════════════════════════════════════════

// Empêche le rafraîchissement automatique (toutes les 20 s) d'écraser une
// modification en cours, non encore enregistrée.
let settingsDirty = false;

function updateSettingsFormVisibility() {
    const detailed = document.getElementById('settings-mode-detailed').checked;
    document.getElementById('settings-detailed-toggles').style.display = detailed ? '' : 'none';
}

async function refreshSettings() {
    if (settingsDirty) return;   // ne pas écraser une modification en cours
    try {
        const s = await fetch(`${API_BASE}/settings/notifications`).then(r => r.json());
        document.getElementById('settings-mode-detailed').checked = s.forex_mode === 'detailed';
        document.getElementById('settings-mode-recap').checked = s.forex_mode === 'daily_recap';
        document.getElementById('settings-entries').checked = !!s.forex_entries_enabled;
        document.getElementById('settings-exits').checked = !!s.forex_exits_enabled;
        document.getElementById('settings-ranking').checked = !!s.forex_ranking_enabled;
        document.getElementById('settings-copytrading-mode-detailed').checked = s.copytrading_mode === 'detailed';
        document.getElementById('settings-copytrading-mode-recap').checked = s.copytrading_mode === 'daily_recap';
        updateSettingsFormVisibility();
    } catch (_) {}
}

document.querySelectorAll('#page-settings input').forEach(input => {
    input.addEventListener('change', () => { settingsDirty = true; });
});

document.querySelectorAll('input[name="settings-forex-mode"]').forEach(radio => {
    radio.addEventListener('change', updateSettingsFormVisibility);
});

document.getElementById('settings-save-btn').addEventListener('click', async () => {
    const statusEl = document.getElementById('settings-save-status');
    const payload = {
        forex_mode: document.getElementById('settings-mode-recap').checked ? 'daily_recap' : 'detailed',
        forex_entries_enabled: document.getElementById('settings-entries').checked,
        forex_exits_enabled: document.getElementById('settings-exits').checked,
        forex_ranking_enabled: document.getElementById('settings-ranking').checked,
        copytrading_mode: document.getElementById('settings-copytrading-mode-recap').checked ? 'daily_recap' : 'detailed',
    };
    try {
        const res = await fetch(`${API_BASE}/settings/notifications`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        statusEl.textContent = res.ok ? '✓ Enregistré' : "Échec de l'enregistrement";
        if (res.ok) settingsDirty = false;
    } catch (_) {
        statusEl.textContent = "Échec de l'enregistrement";
    }
    setTimeout(() => { statusEl.textContent = ''; }, 3000);
});
setInterval(() => showPage(topPageFromHash()), 20000);
