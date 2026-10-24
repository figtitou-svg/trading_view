"""Tests de la présélection des candidats copy trading."""

from copytrading import selector


def _row(addr, account=100000.0, roi_w=0.05, roi_m=0.2, vlm_w=1e6):
    return {"address": addr, "display_name": None, "account_value": account,
            "roi_week": roi_w, "roi_month": roi_m,
            "pnl_week": 0.0, "pnl_month": 0.0, "volume_week": vlm_w}


def test_filtre_les_criteres():
    rows = [
        _row("0xok"),
        _row("0xpetit", account=1000.0),        # < 50 k$
        _row("0xgros", account=5e7),            # > 10 M$
        _row("0xirregulier", roi_w=-0.01),      # ROI 7 j négatif
        _row("0xinactif", vlm_w=0.0),           # aucun volume
    ]
    out = selector.select_candidates(rows)
    assert [r["address"] for r in out] == ["0xok"]


def test_tri_par_roi_mois_et_plafond():
    rows = [_row(f"0x{i:02d}", roi_m=i / 100) for i in range(15)]
    out = selector.select_candidates(rows)
    assert len(out) == 10  # COPY_N_CANDIDATES par défaut
    assert out[0]["address"] == "0x14"          # meilleur ROI 30 j d'abord
    assert out[0]["roi_month"] > out[-1]["roi_month"]
