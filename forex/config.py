"""
forex/config.py — Configuration du module forex, entièrement pilotée par
variables d'environnement (`.env`). **Aucun secret n'est requis** : les
données prix viennent d'un feed public et l'exécution est simulée. Le seul
secret éventuel (token Telegram) vit déjà dans le `.env` du bot crypto et
n'est jamais lu ni loggé ici.

Chaque famille de signal est activable/désactivable indépendamment
(`USE_TECHNICAL`, `USE_FUNDAMENTAL`, `USE_TIME_FILTER`) afin de mesurer sa
contribution marginale à la performance — exigence anti-boîte-noire du spec.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

# ── API Macroéconomiques ─────────────────────────────────
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")


def _floats(name: str, default: str) -> list[float]:
    raw = os.getenv(name, default)
    return [float(x) for x in raw.replace(";", ",").split(",") if x.strip()]


# ── Univers & données ────────────────────────────────────
# Paires au format interne "BASE_QUOTE" (underscore). Mapping vers le feed
# et les conventions de pip géré dans forex.data.prices / forex.risk.sizing.
# Univers par défaut : 7 majeures + 3 crosses très liquides. Réglable via .env
# (chaque paire ajoutée = une requête yfinance de plus par cycle de polling).
_DEFAULT_PAIRS = "EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD,USD_CHF,NZD_USD,EUR_GBP,EUR_JPY,GBP_JPY"
FOREX_PAIRS = [p.strip().upper() for p in
               os.getenv("FOREX_PAIRS", _DEFAULT_PAIRS).split(",") if p.strip()]

# Instruments non-forex tradés chacun par un bot dédié mono-instrument (voir
# forex/strategies/nasdaq_momentum.py, gold_macro.py, oil_breakout.py).
# Format BASE_QUOTE comme le forex, pour rester compatibles avec
# forex.risk.sizing (parse_instrument, pip_size) et forex.risk.manager
# (max_leverage) sans aucune modification de ces modules.
CROSSASSET_INSTRUMENTS = ["NDX_USD", "XAU_USD", "WTI_USD"]

FOREX_DATA_SOURCE = os.getenv("FOREX_DATA_SOURCE", "yfinance").strip().lower()
# Granularité interne (M1, M5, M15, H1, H4, D). Mappée vers l'intervalle du feed.
FOREX_GRANULARITY = os.getenv("FOREX_GRANULARITY", "H1").strip().upper()
FOREX_ACCOUNT_CCY = os.getenv("FOREX_ACCOUNT_CCY", "EUR").strip().upper()

# Répertoire de cache (calendrier éco, portefeuille papier, logs de trades).
FOREX_DATA_DIR = os.getenv(
    "FOREX_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache"),
)

# ── Activation des signaux (confluence) ──────────────────
USE_TECHNICAL = _flag("FOREX_USE_TECHNICAL", "true")
USE_FUNDAMENTAL = _flag("FOREX_USE_FUNDAMENTAL", "true")
USE_TIME_FILTER = _flag("FOREX_USE_TIME_FILTER", "true")

# Mode de la règle de confluence :
#   "strict" = tous les signaux actifs doivent tirer ET s'accorder (cible de
#              recherche : n'entre qu'en vraie confluence, très sélectif) ;
#   "any"    = entre dès qu'un signal actif tire (les signaux qui tirent doivent
#              tout de même s'accorder). Permet d'AVOIR DES TRADES tout de suite
#              (le technique tire immédiatement ; le fondamental s'ajoutera quand
#              l'historique du calendrier sera suffisant).
# Par défaut "any" en paper trading pour générer de l'activité ; le rapport de
# validation (forex.backtest.report) force "strict" pour juger la vraie confluence.
FOREX_CONFLUENCE_MODE = os.getenv("FOREX_CONFLUENCE_MODE", "any").strip().lower()

# ── Bots indépendants (forex/strategies) ─────────────────
# Chaque bot est une stratégie autonome avec SON portefeuille virtuel, SON
# journal de trades et SES paramètres appris (dossier _cache/bots/<id>/).
# Ils tournent en parallèle sur les mêmes bougies et sont comparés entre eux ;
# désactiver un bot ici n'affecte en rien les autres ni leur historique.
#
# Auto-découverte (forex.strategies.registry) : TOUS les bots avec
# `enabled = True` tournent par défaut, sans rien lister ici. FOREX_BOTS ne
# sert plus qu'à RESTREINDRE explicitement à un sous-ensemble (ex. pour
# isoler un bot en test) :
#     FOREX_BOTS=smc,macro
_DEFAULT_BOTS = ""
FOREX_BOTS = [b.strip().lower() for b in
              os.getenv("FOREX_BOTS", _DEFAULT_BOTS).split(",") if b.strip()]

# Bots de COMBINAISON : plusieurs bots de base doivent s'accorder pour entrer
# (cf. forex/strategies/combo.py). Ils ont eux aussi leur propre portefeuille
# et sont jugés en concurrence de leurs membres.
#
# Les 3 premiers croisent une lecture TECHNIQUE avec la lecture MACRO : ce sont
# les plus intéressants en diversification, parce que leurs sources
# d'information sont indépendantes. Les 3 suivants croisent deux lectures
# techniques — plus corrélées, donc a priori moins de valeur ajoutée, mais on
# les mesure au lieu de le supposer. Le dernier exige une majorité des quatre.
_DEFAULT_COMBOS = (
    "trend+macro,chartist+macro,smc+macro,"
    "trend+smc,chartist+smc"
)
FOREX_COMBOS = [c.strip().lower() for c in
                os.getenv("FOREX_COMBOS", _DEFAULT_COMBOS).split(",") if c.strip()]

# ── Variantes SL/TP dynamique (2026-07-23) ───────────────
# Expérience close (2026-07-27) : les variantes de sortie dynamique n'ont pas
# montré d'edge et consommaient RAM/CPU en dupliquant les positions. Le
# mécanisme reste disponible en listant des bots ici via .env.
_DEFAULT_EXIT_VARIANT_BOTS = ""
FOREX_EXIT_VARIANT_BOTS = [b.strip().lower() for b in
                          os.getenv("FOREX_EXIT_VARIANT_BOTS", _DEFAULT_EXIT_VARIANT_BOTS).split(",")
                          if b.strip()]

_DEFAULT_EXIT_VARIANT_MODES = "trailing,trailing_breakeven,chandelier"
FOREX_EXIT_VARIANT_MODES = [m.strip().lower() for m in
                            os.getenv("FOREX_EXIT_VARIANT_MODES", _DEFAULT_EXIT_VARIANT_MODES).split(",")
                            if m.strip()]

# ── Bot SMC (Smart Money Concepts) ───────────────────────
# Fenêtre de recherche des zones d'inefficience (en bougies).
FOREX_SMC_LOOKBACK = int(os.getenv("FOREX_SMC_LOOKBACK", "60"))
# Ancienneté maximale (en bougies) d'une cassure de structure pour que son
# biais soit encore considéré comme valable.
FOREX_SMC_STRUCTURE_LOOKBACK = int(os.getenv("FOREX_SMC_STRUCTURE_LOOKBACK", "30"))
# Taille minimale d'un Fair Value Gap, en multiples d'ATR : en dessous, le
# « trou » relève du bruit de cotation, pas d'un déséquilibre d'ordres.
FOREX_SMC_MIN_FVG_ATR = float(os.getenv("FOREX_SMC_MIN_FVG_ATR", "0.25"))
# Amplitude minimale (en ATR) du corps d'une bougie pour être considérée comme
# une impulsion, et donc désigner un Order Block juste avant elle.
FOREX_SMC_IMPULSE_ATR = float(os.getenv("FOREX_SMC_IMPULSE_ATR", "1.0"))
# Sessions retenues : les inefficiences de liquidité supposent du volume
# institutionnel. Hors Londres/New York, on ne trade pas (conseil « isolez par
# session » — une même logique détruit le capital en session asiatique).
FOREX_SMC_SESSIONS = [s.strip().lower() for s in
                      os.getenv("FOREX_SMC_SESSIONS", "londres,new-york").split(",") if s.strip()]
# Stop plus serré que le défaut : la zone donne l'invalidation du setup.
FOREX_SMC_ATR_STOP_MULT = float(os.getenv("FOREX_SMC_ATR_STOP_MULT", "1.5"))
FOREX_SMC_ATR_TP_MULT = float(os.getenv("FOREX_SMC_ATR_TP_MULT", "4.5"))

# ── Bot macro (modèle quotidien, forex.signals.macro) ────
# Fenêtre (en barres) de mesure de la force relative des devises.
FOREX_MACRO_STRENGTH_BARS = int(os.getenv("FOREX_MACRO_STRENGTH_BARS", "48"))
# Historique (en jours) et fraîcheur du cache des instruments cross-asset.
FOREX_MACRO_LOOKBACK_DAYS = int(os.getenv("FOREX_MACRO_LOOKBACK_DAYS", "10"))
FOREX_MACRO_CACHE_SECONDS = int(os.getenv("FOREX_MACRO_CACHE_SECONDS", "10800"))  # 3 h
# Variation du VIX (%) à partir de laquelle on déclare un régime risk-on/off.
FOREX_MACRO_VIX_THRESHOLD_PCT = float(os.getenv("FOREX_MACRO_VIX_THRESHOLD_PCT", "8.0"))
# Poids des contributions au score d'une devise. Volontairement peu nombreux
# et ronds : chaque facteur a une justification économique, et une grille fine
# serait du sur-ajustement déguisé.
FOREX_MACRO_WEIGHTS = {
    "strength": float(os.getenv("FOREX_MACRO_W_STRENGTH", "1.0")),
    "risk": float(os.getenv("FOREX_MACRO_W_RISK", "0.5")),
    "yield": float(os.getenv("FOREX_MACRO_W_YIELD", "0.5")),
    "oil": float(os.getenv("FOREX_MACRO_W_OIL", "0.3")),
}
# Écart de score entre les deux devises requis pour prendre position.
FOREX_MACRO_THRESHOLD = float(os.getenv("FOREX_MACRO_THRESHOLD", "0.5"))
# Amplification quand une surprise économique confirme le biais du jour.
FOREX_MACRO_EVENT_BOOST = float(os.getenv("FOREX_MACRO_EVENT_BOOST", "1.5"))
# Horizon plus long → stop et objectif plus larges que les autres bots.
FOREX_MACRO_ATR_STOP_MULT = float(os.getenv("FOREX_MACRO_ATR_STOP_MULT", "3.0"))
FOREX_MACRO_ATR_TP_MULT = float(os.getenv("FOREX_MACRO_ATR_TP_MULT", "6.0"))

# ── Bot TSM (momentum temporel) ──────────────────────────
# Fenêtre de calcul du rendement cumulé, en BOUGIES (pas en jours : reste
# cohérent quelle que soit la granularité configurée, contrairement à une
# conversion jours -> bougies qui dépendrait de FOREX_GRANULARITY).
FOREX_TSM_LOOKBACK_BARS = int(os.getenv("FOREX_TSM_LOOKBACK_BARS", "500"))

# ── Signal fondamental (surprise score) ──────────────────
# |score| > seuil (en écarts-types des surprises passées) = surprise significative.
FOREX_SURPRISE_THRESHOLD = float(os.getenv("FOREX_SURPRISE_THRESHOLD", "0.5"))
# Nombre minimum de surprises historiques pour un type d'event avant de lui
# faire confiance (sinon l'écart-type n'est pas fiable → signal ignoré).
FOREX_MIN_SURPRISE_HISTORY = int(os.getenv("FOREX_MIN_SURPRISE_HISTORY", "8"))
# Types d'events suivis (les plus market-moving).
FOREX_TRACKED_EVENTS = [e.strip() for e in os.getenv(
    "FOREX_TRACKED_EVENTS",
    "CPI,Non-Farm Employment Change,GDP,Interest Rate,PMI,Retail Sales,Unemployment Rate",
).split(",") if e.strip()]

# ── Signal technique ─────────────────────────────────────
RSI_PERIOD = int(os.getenv("FOREX_RSI_PERIOD", "14"))
RSI_OVERBOUGHT = float(os.getenv("FOREX_RSI_OVERBOUGHT", "70"))
RSI_OVERSOLD = float(os.getenv("FOREX_RSI_OVERSOLD", "30"))
MACD_FAST = int(os.getenv("FOREX_MACD_FAST", "12"))
MACD_SLOW = int(os.getenv("FOREX_MACD_SLOW", "26"))
MACD_SIGNAL = int(os.getenv("FOREX_MACD_SIGNAL", "9"))
MA_FAST = int(os.getenv("FOREX_MA_FAST", "50"))
MA_SLOW = int(os.getenv("FOREX_MA_SLOW", "200"))

# ── Bot croisement de moyennes mobiles ───────────────────
# Périodes délibérément plus courtes que MA_FAST/MA_SLOW (bot `trend`) pour ne
# pas être une simple redite au ralenti de ce dernier.
FOREX_MA_CROSSOVER_FAST = int(os.getenv("FOREX_MA_CROSSOVER_FAST", "20"))
FOREX_MA_CROSSOVER_SLOW = int(os.getenv("FOREX_MA_CROSSOVER_SLOW", "100"))

# ── Bot cassure de canal ──────────────────────────────────
FOREX_CHANNEL_BREAKOUT_BARS = int(os.getenv("FOREX_CHANNEL_BREAKOUT_BARS", "20"))

# ── Bot cassure Londres ───────────────────────────────────
# Fenêtre (en heures depuis l'ouverture Londres, 7h UTC) pendant laquelle une
# cassure du range Tokyo est encore considérée comme une entrée valide.
FOREX_LONDON_BREAKOUT_WINDOW_HOURS = int(os.getenv("FOREX_LONDON_BREAKOUT_WINDOW_HOURS", "4"))

# Figures chartistes classiques (forex.signals.patterns) : détection sur points
# de swing (fractals). Tolérances exprimées en multiples d'ATR (pas de % fixes)
# pour rester cohérentes entre paires.
FOREX_SWING_LEFT = int(os.getenv("FOREX_SWING_LEFT", "3"))
FOREX_SWING_RIGHT = int(os.getenv("FOREX_SWING_RIGHT", "3"))
FOREX_PATTERN_TOLERANCE_ATR = float(os.getenv("FOREX_PATTERN_TOLERANCE_ATR", "0.5"))
FOREX_PATTERN_LOOKBACK = int(os.getenv("FOREX_PATTERN_LOOKBACK", "60"))

# ── Filtre temporel (autour des annonces) ────────────────
# Pas de NOUVELLE position dans les N minutes précédant un event high-impact.
EXCLUSION_MIN_BEFORE = int(os.getenv("FOREX_EXCLUSION_MIN_BEFORE", "15"))
# Spread élargi (et volatilité) considéré pendant N minutes après l'annonce.
EXCLUSION_MIN_AFTER = int(os.getenv("FOREX_EXCLUSION_MIN_AFTER", "5"))
# Sortie forcée d'un trade event-driven après N minutes sans mouvement utile.
# (Ne concerne QUE les trades réellement déclenchés par une surprise macro.)
EVENT_TRADE_MAX_MIN = int(os.getenv("FOREX_EVENT_TRADE_MAX_MIN", "120"))
# Filet de sécurité : détention absolue maximale (en BARRES), tous trades
# confondus, pour éviter qu'une position stagne indéfiniment sans toucher
# stop/TP. Généreux (≈ plusieurs jours en H1) pour ne pas couper un trade
# technique encore en route vers son objectif.
MAX_HOLD_BARS = int(os.getenv("FOREX_MAX_HOLD_BARS", "200"))
# Facteur d'élargissement du spread appliqué juste après une annonce.
POST_EVENT_SPREAD_MULT = float(os.getenv("FOREX_POST_EVENT_SPREAD_MULT", "5.0"))

# ── Gestion du risque ────────────────────────────────────
FOREX_RISK_PCT = float(os.getenv("FOREX_RISK_PCT", "1.0"))          # % du capital risqué/trade
FOREX_DAILY_LOSS_LIMIT_PCT = float(os.getenv("FOREX_DAILY_LOSS_LIMIT_PCT", "3.0"))
FOREX_WEEKLY_LOSS_LIMIT_PCT = float(os.getenv("FOREX_WEEKLY_LOSS_LIMIT_PCT", "6.0"))
FOREX_TRAILING_DD_PCT = float(os.getenv("FOREX_TRAILING_DD_PCT", "10.0"))

ATR_PERIOD = int(os.getenv("FOREX_ATR_PERIOD", "14"))
ATR_STOP_MULT = float(os.getenv("FOREX_ATR_STOP_MULT", "2.0"))
ATR_TP_MULT = float(os.getenv("FOREX_ATR_TP_MULT", "3.0"))

# ── Coûts (backtest & paper) ─────────────────────────────
FOREX_SPREAD_PIPS = float(os.getenv("FOREX_SPREAD_PIPS", "0.8"))    # spread bid/ask moyen
FOREX_SLIPPAGE_PIPS = float(os.getenv("FOREX_SLIPPAGE_PIPS", "0.3"))
FOREX_SWAP_PIPS_PER_DAY = float(os.getenv("FOREX_SWAP_PIPS_PER_DAY", "0.2"))  # coût overnight
# Commission explicite, en plus du spread : les brokers ECN facturent en plus
# un montant fixe par lot (ex. 6 $ / lot standard round-turn). Convertie en
# pips-équivalent pour rester dans la même unité que les autres coûts :
# 6 $ / (100 000 unités × 0,0001 $/pip sur une paire cotée USD) ≈ 0,6 pip.
FOREX_COMMISSION_PIPS = float(os.getenv("FOREX_COMMISSION_PIPS", "0.6"))

# ── Paper trading ────────────────────────────────────────
FOREX_START_EQUITY = float(os.getenv("FOREX_START_EQUITY", "10000"))
FOREX_POLL_SECONDS = int(os.getenv("FOREX_POLL_SECONDS", "60"))

# ── Apprentissage (module 7) ─────────────────────────────
# Échantillon minimum par combinaison de signaux avant toute désactivation /
# réactivation (distingue le bruit d'une vraie dégradation).
FOREX_LEARN_MIN_SAMPLE = int(os.getenv("FOREX_LEARN_MIN_SAMPLE", "15"))
# Ré-analyse des combos à chaque palier de N trades clôturés.
FOREX_LEARN_TRADE_PALIER = int(os.getenv("FOREX_LEARN_TRADE_PALIER", "30"))
# Seuil de significativité (t-test pnl vs 0) pour désactiver/réactiver un combo.
FOREX_LEARN_ALPHA = float(os.getenv("FOREX_LEARN_ALPHA", "0.05"))
# Auto-tuner walk-forward : nombre de folds minimum, ratio de folds positifs
# minimum, et marge d'amélioration OOS (%) exigée pour changer un paramètre.
FOREX_LEARN_MIN_FOLDS = int(os.getenv("FOREX_LEARN_MIN_FOLDS", "3"))
FOREX_LEARN_POSITIVE_FOLD_RATIO = float(os.getenv("FOREX_LEARN_POSITIVE_FOLD_RATIO", "0.6"))
FOREX_LEARN_OOS_MARGIN_PCT = float(os.getenv("FOREX_LEARN_OOS_MARGIN_PCT", "1.0"))

# ── Portail de verdict par bot (spec 2026-07-27) ─────────
# Un bot est jugé sur ses trades LIVE ; le backtest ne peut à lui seul le tuer.
FOREX_VERDICT_MIN_LIVE_TRADES = int(os.getenv("FOREX_VERDICT_MIN_LIVE_TRADES", "30"))
FOREX_VERDICT_PF_VALIDATED = float(os.getenv("FOREX_VERDICT_PF_VALIDATED", "1.15"))
FOREX_VERDICT_KILL_BACKTEST_PF = float(os.getenv("FOREX_VERDICT_KILL_BACKTEST_PF", "0.95"))
FOREX_VERDICT_KILL_MIN_LIVE = int(os.getenv("FOREX_VERDICT_KILL_MIN_LIVE", "20"))
FOREX_VERDICT_KILL_DD_PCT = float(os.getenv("FOREX_VERDICT_KILL_DD_PCT", "15.0"))
# Multiplicateur de risque par statut (appliqué au sizing du runner).
FOREX_VERDICT_RISK_MULT = {
    "incubation": float(os.getenv("FOREX_VERDICT_MULT_INCUBATION", "0.25")),
    "watch": float(os.getenv("FOREX_VERDICT_MULT_WATCH", "0.5")),
    "validated": float(os.getenv("FOREX_VERDICT_MULT_VALIDATED", "1.0")),
    "kill": 0.0,
}


def summary() -> str:
    """Résumé lisible de la config active (pour les logs de démarrage)."""
    signals = [n for n, on in (
        ("technique", USE_TECHNICAL),
        ("fondamental", USE_FUNDAMENTAL),
        ("filtre-temporel", USE_TIME_FILTER),
    ) if on]
    return (
        f"Paires={','.join(FOREX_PAIRS)} · granularité={FOREX_GRANULARITY} · "
        f"signaux actifs={'+'.join(signals) or 'AUCUN'} · mode={FOREX_CONFLUENCE_MODE} · "
        f"risque/trade={FOREX_RISK_PCT}% · capital simulé={FOREX_START_EQUITY:.0f} {FOREX_ACCOUNT_CCY}"
    )
