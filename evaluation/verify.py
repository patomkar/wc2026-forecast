"""
Forecast verification for the WC2026 model.

Scoring rules
-------------
RPS      Ranked Probability Score (Epstein 1969; Constantinou & Fenton 2012).
         Proper, non-local, sensitive to distance -- the field standard for 1X2.
Brier    Multiclass Brier score, plus Murphy (1973) reliability/resolution/uncertainty.
Log loss Ignorance score. Proper and local (Wheatcroft 2021 argues it is preferable
         for model selection); reported alongside RPS rather than instead of it.

Benchmarks: uniform (1/3 each) and climatology (observed outcome base rates).
Uncertainty: nonparametric bootstrap over matches.

Usage:
    python evaluation/verify.py --forecast forecast/output/probabilities.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

OUTCOMES = ("a_win", "draw", "b_win")


# ---------------------------------------------------------------- scoring rules
def rps(p: np.ndarray, o: np.ndarray) -> float:
    """Ranked Probability Score, normalised by (r-1). Lower is better."""
    cp, co = np.cumsum(p, axis=1)[:, :-1], np.cumsum(o, axis=1)[:, :-1]
    return float((((cp - co) ** 2).sum(axis=1) / (p.shape[1] - 1)).mean())


def brier(p: np.ndarray, o: np.ndarray) -> float:
    return float(((p - o) ** 2).sum(axis=1).mean())


def log_loss(p: np.ndarray, o: np.ndarray) -> float:
    return float(-np.log(np.clip((p * o).sum(axis=1), 1e-12, 1)).mean())


def accuracy(p: np.ndarray, o: np.ndarray) -> float:
    return float((p.argmax(1) == o.argmax(1)).mean())


def skill(score: float, reference: float) -> float:
    """Skill score: 1 - score/reference. Positive means better than reference."""
    return 1 - score / reference


def murphy(p_flat: np.ndarray, o_flat: np.ndarray, bins) -> dict:
    """Murphy (1973) decomposition: Brier = reliability - resolution + uncertainty."""
    obar = o_flat.mean()
    rel = res = 0.0
    table = []
    for lo, hi in bins:
        m = (p_flat >= lo) & (p_flat < hi)
        if not m.any():
            continue
        mp, ob = p_flat[m].mean(), o_flat[m].mean()
        rel += m.sum() * (mp - ob) ** 2
        res += m.sum() * (ob - obar) ** 2
        table.append({"bin": f"{lo:.2f}-{hi:.2f}", "n": int(m.sum()),
                      "mean_forecast": mp, "observed": ob, "gap": ob - mp})
    n = len(p_flat)
    return {"reliability": rel / n, "resolution": res / n,
            "uncertainty": obar * (1 - obar), "table": table}


# ---------------------------------------------------------------- data loading
def load(forecast_path: Path, results_path: Path):
    fc = json.loads(forecast_path.read_text())
    with open(results_path) as f:
        results = list(csv.DictReader(f))

    actual = {}
    for r in results:
        if r["stage"] != "GROUP":
            continue
        actual[frozenset((r["team_a"], r["team_b"]))] = (
            r["team_a"], int(r["goals_a"]), r["team_b"], int(r["goals_b"]))

    P, O, meta = [], [], []
    for m in fc["group_matches"]:
        key = frozenset((m["team_a"], m["team_b"]))
        if key not in actual:
            raise KeyError(f"no result for {m['team_a']} vs {m['team_b']}")
        ta, ga, tb, gb = actual[key]
        if ta == m["team_a"]:
            ha, hb = ga, gb
        else:
            ha, hb = gb, ga
        idx = 0 if ha > hb else (1 if ha == hb else 2)
        P.append([m["p_a_win"], m["p_draw"], m["p_b_win"]])
        O.append([1 if i == idx else 0 for i in range(3)])
        meta.append({**m, "goals_a": ha, "goals_b": hb, "outcome": OUTCOMES[idx]})

    P = np.asarray(P, dtype=float)
    P /= P.sum(axis=1, keepdims=True)
    return fc, P, np.asarray(O, dtype=float), meta, results


# ---------------------------------------------------------------- report
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forecast", default="forecast/output/probabilities.json")
    ap.add_argument("--results", default="data/results_actual.csv")
    ap.add_argument("--bootstrap", type=int, default=10_000)
    ap.add_argument("--json-out", default="evaluation/metrics.json")
    args = ap.parse_args()

    fc, P, O, meta, results = load(Path(args.forecast), Path(args.results))
    n = len(P)
    uniform = np.full_like(P, 1 / 3)
    climatology = np.tile(O.mean(axis=0), (n, 1))

    print("=" * 68)
    print(f"GROUP-STAGE MATCH FORECASTS  (n={n}, three ordinal outcomes)")
    print("=" * 68)
    print(f"{'':16}{'RPS':>9}{'Brier':>9}{'LogLoss':>10}{'Acc':>8}")
    scores = {}
    for name, p in [("Model", P), ("Uniform", uniform), ("Climatology", climatology)]:
        scores[name] = dict(rps=rps(p, O), brier=brier(p, O),
                            log_loss=log_loss(p, O), accuracy=accuracy(p, O))
        s = scores[name]
        print(f"{name:16}{s['rps']:>9.4f}{s['brier']:>9.4f}"
              f"{s['log_loss']:>10.4f}{s['accuracy']:>8.1%}")

    print(f"\nRPS skill vs uniform      {skill(scores['Model']['rps'], scores['Uniform']['rps']):+.2%}")
    print(f"RPS skill vs climatology  {skill(scores['Model']['rps'], scores['Climatology']['rps']):+.2%}")
    print(f"Brier skill vs uniform    {skill(scores['Model']['brier'], scores['Uniform']['brier']):+.2%}")

    # bootstrap
    rng = np.random.default_rng(1)
    idx = rng.integers(0, n, size=(args.bootstrap, n))
    b_rps = np.array([rps(P[i], O[i]) for i in idx])
    b_ll = np.array([log_loss(P[i], O[i]) for i in idx])
    b_gain = np.array([rps(uniform[i], O[i]) - rps(P[i], O[i]) for i in idx])
    print(f"\nBootstrap ({args.bootstrap:,} resamples)")
    print(f"  RPS      {scores['Model']['rps']:.4f}  95% CI [{np.percentile(b_rps, 2.5):.4f}, {np.percentile(b_rps, 97.5):.4f}]")
    print(f"  LogLoss  {scores['Model']['log_loss']:.4f}  95% CI [{np.percentile(b_ll, 2.5):.4f}, {np.percentile(b_ll, 97.5):.4f}]")
    print(f"  Gain vs uniform {b_gain.mean():.4f}  95% CI "
          f"[{np.percentile(b_gain, 2.5):.4f}, {np.percentile(b_gain, 97.5):.4f}]  P(>0)={np.mean(b_gain > 0):.3f}")

    # calibration
    bins = [(0, .10), (.10, .25), (.25, .45), (.45, .65), (.65, 1.01)]
    dec = murphy(P.flatten(), O.flatten(), bins)
    print(f"\nCALIBRATION ({P.size} outcome probabilities)")
    print(f"  {'bin':<12}{'n':>5}{'forecast':>11}{'observed':>11}{'gap':>9}")
    for row in dec["table"]:
        print(f"  {row['bin']:<12}{row['n']:>5}{row['mean_forecast']:>11.1%}"
              f"{row['observed']:>11.1%}{row['gap']:>+9.1%}")
    print(f"\n  Brier {dec['reliability'] - dec['resolution'] + dec['uncertainty']:.4f}"
          f" = reliability {dec['reliability']:.4f}"
          f" - resolution {dec['resolution']:.4f}"
          f" + uncertainty {dec['uncertainty']:.4f}")

    # sharpness diagnostic
    print("\nTEMPERATURE DIAGNOSTIC (T<1 sharpens; identifies under-confidence)")
    grid = np.linspace(0.4, 1.6, 241)
    curve = []
    for T in grid:
        Q = P ** (1 / T)
        Q /= Q.sum(axis=1, keepdims=True)
        curve.append(rps(Q, O))
    t_opt = float(grid[int(np.argmin(curve))])
    for T in (0.6, 0.8, 1.0, 1.2, 1.4):
        Q = P ** (1 / T); Q /= Q.sum(axis=1, keepdims=True)
        print(f"  T={T:.1f}  RPS {rps(Q, O):.4f}  LogLoss {log_loss(Q, O):.4f}")
    print(f"  optimal T={t_opt:.2f} -> RPS {min(curve):.4f} "
          f"({skill(min(curve), scores['Model']['rps']):+.1%}). "
          f"{'UNDER' if t_opt < 1 else 'OVER'}-confident.")
    print("  NOTE: fit on the evaluation sample. Diagnostic only; not applied above.")

    # goal model
    xg = np.array([[m["xg_a"], m["xg_b"]] for m in meta])
    ag = np.array([[m["goals_a"], m["goals_b"]] for m in meta], dtype=float)
    flat = ag.flatten()
    print("\nGOAL MODEL")
    print(f"  Total goals: predicted {xg.sum():.0f}, actual {ag.sum():.0f} "
          f"({(ag.sum() - xg.sum()) / xg.sum():+.1%})")
    print(f"  MAE {np.abs(xg - ag).mean():.3f} | RMSE {np.sqrt(((xg - ag) ** 2).mean()):.3f} "
          f"| corr {np.corrcoef(xg.flatten(), flat)[0, 1]:.3f}")
    print(f"  Dispersion: mean {flat.mean():.3f}, variance {flat.var():.3f}, "
          f"ratio {flat.var() / flat.mean():.2f} (Poisson requires 1.00)")

    # advancement
    stages = build_stage_truth(results)
    print("\n" + "=" * 68)
    print("TOURNAMENT ADVANCEMENT FORECASTS (48 teams)")
    print("=" * 68)
    print(f"  {'Stage':<14}{'Brier':>8}{'BaseRate':>10}{'BSS':>9}{'Top-N':>9}")
    T = fc["teams"]
    tot_m = tot_b = 0.0
    adv = {}
    for key, truth, label, topn in stages:
        b = sum((T[t][key] - (t in truth)) ** 2 for t in T) / len(T)
        rate = len(truth) / len(T)
        ref = sum((rate - (t in truth)) ** 2 for t in T) / len(T)
        hit = len(set(sorted(T, key=lambda t: -T[t][key])[:topn]) & truth)
        adv[label] = {"brier": b, "reference": ref, "bss": skill(b, ref),
                      "top_n_hit": hit, "top_n": topn}
        print(f"  {label:<14}{b:>8.4f}{ref:>10.4f}{skill(b, ref):>+9.1%}{f'{hit}/{topn}':>9}")
        tot_m += b; tot_b += ref
    k = len(stages)
    print(f"  {'AGGREGATE':<14}{tot_m / k:>8.4f}{tot_b / k:>10.4f}{skill(tot_m, tot_b):>+9.1%}")

    champion = next(t for t in T if t in stages[-1][1])
    print(f"\nCHAMPION LOG SCORE (lower is better)")
    print(f"  Model   p({champion})={T[champion]['P_champion']:.1%} -> {-math.log(T[champion]['P_champion']):.4f}")
    print(f"  Market  p({champion})=16.4%  -> {-math.log(0.164):.4f}")
    print(f"  Uniform 1/48              -> {-math.log(1 / 48):.4f}")

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps({
        "n_group_matches": n, "match_scores": scores,
        "rps_skill_vs_uniform": skill(scores["Model"]["rps"], scores["Uniform"]["rps"]),
        "rps_skill_vs_climatology": skill(scores["Model"]["rps"], scores["Climatology"]["rps"]),
        "bootstrap": {"rps_ci": [float(np.percentile(b_rps, 2.5)), float(np.percentile(b_rps, 97.5))],
                      "log_loss_ci": [float(np.percentile(b_ll, 2.5)), float(np.percentile(b_ll, 97.5))],
                      "p_gain_positive": float(np.mean(b_gain > 0))},
        "calibration": dec, "optimal_temperature": t_opt,
        "goal_model": {"predicted": float(xg.sum()), "actual": float(ag.sum()),
                       "dispersion_ratio": float(flat.var() / flat.mean())},
        "advancement": adv,
    }, indent=1, default=float))
    print(f"\nWrote {args.json_out}")


def build_stage_truth(results):
    """Derive which teams reached each stage from the results file."""
    def played(stage):
        s = set()
        for r in results:
            if r["stage"] == stage:
                s.add(r["team_a"]); s.add(r["team_b"])
        return s

    def winners(stage):
        s = set()
        for r in results:
            if r["stage"] != stage:
                continue
            note = r["notes"]
            if "pens" in note:
                s.add(note.split()[0])  # 3-letter code resolved below
                continue
            s.add(r["team_a"] if int(r["goals_a"]) > int(r["goals_b"]) else r["team_b"])
        return s

    CODE = {"PAR": "Paraguay", "MAR": "Morocco", "EGY": "Egypt", "SUI": "Switzerland"}
    def resolve(s):
        return {CODE.get(x, x) for x in s}

    r32, r16, qf = played("R32"), played("R16"), played("QF")
    sf, final = played("SF"), played("FINAL")
    champ = resolve(winners("FINAL"))

    # group winners and qualifiers from the group table
    from collections import defaultdict
    pts, gd, gf = defaultdict(int), defaultdict(int), defaultdict(int)
    grp = {}
    for r in results:
        if r["stage"] != "GROUP":
            continue
        a, b = r["team_a"], r["team_b"]
        ga, gb = int(r["goals_a"]), int(r["goals_b"])
        grp[a] = grp[b] = r["group"]
        pts[a] += 3 if ga > gb else (1 if ga == gb else 0)
        pts[b] += 3 if gb > ga else (1 if ga == gb else 0)
        gd[a] += ga - gb; gd[b] += gb - ga
        gf[a] += ga; gf[b] += gb
    by_group = defaultdict(list)
    for t, g in grp.items():
        by_group[g].append(t)
    group_winners = set()
    for g, ts in by_group.items():
        group_winners.add(sorted(ts, key=lambda t: (-pts[t], -gd[t], -gf[t]))[0])

    return [
        ("P_win_group", group_winners, "Win group", 12),
        ("P_qualify", r32, "Qualify", 32),
        ("P_r16", r16, "Reach R16", 16),
        ("P_qf", qf, "Reach QF", 8),
        ("P_sf", sf, "Reach SF", 4),
        ("P_final", final, "Reach final", 2),
        ("P_champion", champ, "Champion", 1),
    ]


if __name__ == "__main__":
    main()
