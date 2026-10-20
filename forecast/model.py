"""
FIFA World Cup 2026 forecast model.

Pipeline:  frozen ratings -> Poisson goal model -> 100,000 Monte Carlo tournaments

The ratings in data/ratings_20260610.csv were frozen on 10 June 2026, before the
opening match. This script consumes them and emits the probability tables that
evaluation/verify.py scores. Nothing here is refit on observed results.

Usage:
    python forecast/model.py --sims 100000 --out forecast/output/probabilities.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# Model hyperparameters (frozen 2026-06-10; see MODEL_EVALUATION.md §5 for
# post-hoc diagnostics showing SHRINK was too aggressive and GOAL_BASE too low)
# --------------------------------------------------------------------------
MEAN_RATING = 1830.0   # centre of the rating distribution
SHRINK = 0.72          # compress rating gaps toward the mean (market-dispersion calibration)
RATING_PER_GOAL = 195.0  # rating points per 1.0 expected-goal-difference
GOAL_BASE = 1.25       # baseline expected goals per team per match
HOST_DECAY_KO = 0.75   # fraction of host bonus retained in knockout rounds
ET_INTENSITY = 1 / 3   # extra-time scoring rate relative to regulation
PEN_TILT = 4000.0      # rating points per unit of shootout win-probability tilt

GROUPS_ORDER = list("ABCDEFGHIJKL")

# Round of 32 bracket per FIFA schedule. ("1","E") = winner of group E;
# ("3","ABCDF") = a third-placed team from one of those groups.
R32_SLOTS = [
    ("M73", ("2", "A"), ("2", "B")),
    ("M74", ("1", "E"), ("3", "ABCDF")),
    ("M75", ("1", "F"), ("2", "C")),
    ("M76", ("1", "C"), ("2", "F")),
    ("M77", ("1", "I"), ("3", "CDFGH")),
    ("M78", ("2", "E"), ("2", "I")),
    ("M79", ("1", "A"), ("3", "CEFHI")),
    ("M80", ("1", "L"), ("3", "EHIJK")),
    ("M81", ("1", "D"), ("3", "BEFIJ")),
    ("M82", ("1", "G"), ("3", "AEHIJ")),
    ("M83", ("2", "K"), ("2", "L")),
    ("M84", ("1", "H"), ("2", "J")),
    ("M85", ("1", "B"), ("3", "EFGIJ")),
    ("M86", ("1", "J"), ("2", "H")),
    ("M87", ("1", "K"), ("3", "DEIJL")),
    ("M88", ("2", "D"), ("2", "G")),
]
R16_SLOTS = [("M89", "M74", "M77"), ("M90", "M73", "M75"), ("M91", "M76", "M78"),
             ("M92", "M79", "M80"), ("M93", "M83", "M84"), ("M94", "M81", "M82"),
             ("M95", "M86", "M88"), ("M96", "M85", "M87")]
QF_SLOTS = [("M97", "M89", "M90"), ("M98", "M93", "M94"),
            ("M99", "M91", "M92"), ("M100", "M95", "M96")]
SF_SLOTS = [("M101", "M97", "M98"), ("M102", "M99", "M100")]


def load_ratings(path: Path) -> tuple[dict, dict]:
    """Return (ratings dict, groups dict) from the frozen CSV."""
    ratings, groups = {}, defaultdict(list)
    with open(path) as f:
        for row in csv.DictReader(f):
            ratings[row["team"]] = (float(row["rating"]), float(row["host_adj"]))
            groups[row["group"]].append(row["team"])
    return ratings, dict(groups)


class Model:
    def __init__(self, ratings: dict, groups: dict):
        self.R = ratings
        self.groups = groups

    def effective(self, team: str, knockout: bool = False) -> float:
        """Shrunk rating plus host bonus (decayed in knockouts)."""
        rating, host = self.R[team]
        bonus = host * (HOST_DECAY_KO if knockout else 1.0)
        return MEAN_RATING + (rating - MEAN_RATING) * SHRINK + bonus

    def lambdas(self, a: str, b: str, knockout: bool = False) -> tuple[float, float]:
        """Poisson means for (a, b). Gap -> expected goal difference."""
        egd = (self.effective(a, knockout) - self.effective(b, knockout)) / RATING_PER_GOAL
        bump = 0.04 * abs(egd)   # mismatches are slightly higher-scoring overall
        return (max(0.18, GOAL_BASE + egd / 2 + bump),
                max(0.18, GOAL_BASE - egd / 2 + bump))

    def outcome_probs(self, a: str, b: str, knockout: bool = False, maxg: int = 16) -> dict:
        """Poisson 1X2 probabilities plus modal scoreline.

        The scoreline grid is truncated at `maxg` goals, which discards a small
        amount of probability mass (~1e-6 at maxg=16 for the most lopsided
        fixture in the field). Outcome probabilities are renormalised so they
        sum to exactly 1; p_modal is left on the raw scale.
        """
        la, lb = self.lambdas(a, b, knockout)
        pa = [math.exp(-la) * la ** k / math.factorial(k) for k in range(maxg)]
        pb = [math.exp(-lb) * lb ** k / math.factorial(k) for k in range(maxg)]
        win = draw = loss = 0.0
        best, best_p = (0, 0), 0.0
        for i in range(maxg):
            for j in range(maxg):
                p = pa[i] * pb[j]
                if i > j:
                    win += p
                elif i == j:
                    draw += p
                else:
                    loss += p
                if p > best_p:
                    best_p, best = p, (i, j)
        total = win + draw + loss
        return {"win": win / total, "draw": draw / total, "loss": loss / total,
                "xg_a": la, "xg_b": lb,
                "modal_score": f"{best[0]}-{best[1]}", "p_modal": best_p}

    def knockout_match(self, a: str, b: str) -> tuple[str, bool, bool]:
        """Simulate one knockout tie. Returns (winner, went_to_et, went_to_pens)."""
        la, lb = self.lambdas(a, b, knockout=True)
        ga, gb = _poisson(la), _poisson(lb)
        if ga != gb:
            return (a if ga > gb else b), False, False
        ea, eb = _poisson(la * ET_INTENSITY), _poisson(lb * ET_INTENSITY)
        if ea != eb:
            return (a if ea > eb else b), True, False
        tilt = 0.5 + (self.effective(a, True) - self.effective(b, True)) / PEN_TILT
        return (a if random.random() < tilt else b), True, True


def _poisson(lam: float) -> int:
    """Knuth sampler (uses the `random` stream so knockout sims are seed-reproducible)."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= random.random()
        if p <= limit:
            return k
        k += 1


def group_fixtures(teams: list[str]) -> list[tuple[str, str]]:
    """Round robin. Order is irrelevant to the simulation."""
    t = teams
    return [(t[0], t[1]), (t[2], t[3]), (t[0], t[2]),
            (t[3], t[1]), (t[3], t[0]), (t[1], t[2])]


def simulate(model: Model, n_sims: int, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    random.seed(seed + 1)

    teams = list(model.R)
    tidx = {t: i for i, t in enumerate(teams)}
    fixtures = [(g, a, b) for g in GROUPS_ORDER for a, b in group_fixtures(model.groups[g])]

    # ---- group stage, vectorised ----
    lam = np.array([model.lambdas(a, b)[:2] for _, a, b in fixtures])
    goals = rng.poisson(lam[:, :, None], size=(len(fixtures), 2, n_sims))

    pts = np.zeros((len(teams), n_sims), dtype=np.int16)
    gf = np.zeros((len(teams), n_sims), dtype=np.int16)
    ga_ = np.zeros((len(teams), n_sims), dtype=np.int16)
    for m, (_, a, b) in enumerate(fixtures):
        Ga, Gb = goals[m, 0], goals[m, 1]
        ia, ib = tidx[a], tidx[b]
        pts[ia] += np.where(Ga > Gb, 3, np.where(Ga == Gb, 1, 0)).astype(np.int16)
        pts[ib] += np.where(Gb > Ga, 3, np.where(Ga == Gb, 1, 0)).astype(np.int16)
        gf[ia] += Ga; ga_[ia] += Gb
        gf[ib] += Gb; ga_[ib] += Ga
    gd = gf - ga_

    # lexicographic rank key: points, then GD, then GF, then random tiebreak
    key = (pts.astype(np.float64) * 1_000_000
           + (gd.astype(np.float64) + 200) * 1_000
           + gf.astype(np.float64) * 2
           + rng.random((len(teams), n_sims)))

    order = {}
    for g in GROUPS_ORDER:
        idxs = np.array([tidx[t] for t in model.groups[g]])
        order[g] = idxs[np.argsort(-key[idxs], axis=0)]

    # eight best third-placed teams
    thirds = np.stack([order[g][2] for g in GROUPS_ORDER])
    third_key = key[thirds, np.arange(n_sims)[None, :]]
    ranked = np.argsort(-third_key, axis=0)
    third_qualifies = np.zeros((12, n_sims), dtype=bool)
    for pos in range(8):
        third_qualifies[ranked[pos], np.arange(n_sims)] = True

    # ---- knockouts ----
    stage = {t: defaultdict(int) for t in teams}
    position = {t: [0, 0, 0, 0] for t in teams}
    slot_winners = defaultdict(lambda: defaultdict(int))
    final_pairs = defaultdict(int)
    et_count = pen_count = ko_count = 0

    ord_T = {g: order[g].T for g in GROUPS_ORDER}
    q3_T = third_qualifies.T
    third_slot_pools = [(lbl, (s1 if s1[0] == "3" else s2)[1])
                        for lbl, s1, s2 in R32_SLOTS if s1[0] == "3" or s2[0] == "3"]

    for s in range(n_sims):
        slot = {}
        for g in GROUPS_ORDER:
            o = ord_T[g][s]
            slot[("1", g)] = teams[o[0]]
            slot[("2", g)] = teams[o[1]]
            for k in range(4):
                position[teams[o[k]]][k] += 1

        qualified_thirds = {GROUPS_ORDER[i] for i in range(12) if q3_T[s][i]}
        for g in qualified_thirds:
            stage[teams[ord_T[g][s][2]]]["qual_third"] += 1

        # assign thirds to slots, most-constrained-first (approximates FIFA Annex C)
        remaining = set(qualified_thirds)
        assigned = {}
        for _ in range(8):
            cands = [(sum(1 for g in remaining if g in pool), lbl, pool)
                     for lbl, pool in third_slot_pools if lbl not in assigned]
            cands.sort()
            _, lbl, pool = cands[0]
            eligible = [g for g in remaining if g in pool] or list(remaining)
            pick = eligible[0]
            assigned[lbl] = teams[ord_T[pick][s][2]]
            remaining.discard(pick)

        winners = {}
        for lbl, s1, s2 in R32_SLOTS:
            a = assigned[lbl] if s1[0] == "3" else slot[s1]
            b = assigned[lbl] if s2[0] == "3" else slot[s2]
            stage[a]["r32"] += 1
            stage[b]["r32"] += 1
            w, et, pen = model.knockout_match(a, b)
            ko_count += 1; et_count += et; pen_count += pen
            winners[lbl] = w
            slot_winners[lbl][w] += 1

        for slots, name in [(R16_SLOTS, "r16"), (QF_SLOTS, "qf"), (SF_SLOTS, "sf")]:
            for lbl, m1, m2 in slots:
                a, b = winners[m1], winners[m2]
                stage[a][name] += 1
                stage[b][name] += 1
                w, et, pen = model.knockout_match(a, b)
                ko_count += 1; et_count += et; pen_count += pen
                winners[lbl] = w
                slot_winners[lbl][w] += 1

        fa, fb = winners["M101"], winners["M102"]
        stage[fa]["final"] += 1
        stage[fb]["final"] += 1
        final_pairs[tuple(sorted((fa, fb)))] += 1
        champion, _, _ = model.knockout_match(fa, fb)
        stage[champion]["champion"] += 1

    # ---- assemble output ----
    out = {
        "n_sims": n_sims,
        "seed": seed,
        "hyperparameters": {
            "MEAN_RATING": MEAN_RATING, "SHRINK": SHRINK,
            "RATING_PER_GOAL": RATING_PER_GOAL, "GOAL_BASE": GOAL_BASE,
            "HOST_DECAY_KO": HOST_DECAY_KO, "ET_INTENSITY": ET_INTENSITY,
        },
        "teams": {}, "group_matches": [],
        "slot_winners": {lbl: sorted(d.items(), key=lambda kv: -kv[1])[:6]
                         for lbl, d in slot_winners.items()},
        "final_pairs": sorted(([list(k), v] for k, v in final_pairs.items()),
                              key=lambda kv: -kv[1])[:12],
        "extra_time_rate": et_count / ko_count,
        "penalty_rate": pen_count / ko_count,
    }
    for t in teams:
        i = tidx[t]
        p1 = position[t][0] / n_sims
        p2 = position[t][1] / n_sims
        p3q = stage[t]["qual_third"] / n_sims
        out["teams"][t] = {
            "rating": model.R[t][0], "host_adj": model.R[t][1],
            "exp_points": round(float(pts[i].mean()), 3),
            "exp_gf": round(float(gf[i].mean()), 3),
            "exp_ga": round(float(ga_[i].mean()), 3),
            "P_win_group": round(p1, 4), "P_second": round(p2, 4),
            "P_qual_third": round(p3q, 4), "P_qualify": round(p1 + p2 + p3q, 4),
            "P_r32": round(stage[t]["r32"] / n_sims, 4),
            "P_r16": round(stage[t]["r16"] / n_sims, 4),
            "P_qf": round(stage[t]["qf"] / n_sims, 4),
            "P_sf": round(stage[t]["sf"] / n_sims, 4),
            "P_final": round(stage[t]["final"] / n_sims, 4),
            "P_champion": round(stage[t]["champion"] / n_sims, 4),
        }
    for g, a, b in fixtures:
        p = model.outcome_probs(a, b)
        out["group_matches"].append({
            "group": g, "team_a": a, "team_b": b,
            "p_a_win": round(p["win"], 4), "p_draw": round(p["draw"], 4),
            "p_b_win": round(p["loss"], 4),
            "xg_a": round(p["xg_a"], 3), "xg_b": round(p["xg_b"], 3),
            "modal_score": p["modal_score"], "p_modal": round(p["p_modal"], 4),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the WC2026 forecast model.")
    ap.add_argument("--ratings", default="data/ratings_20260610.csv")
    ap.add_argument("--sims", type=int, default=100_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="forecast/output/probabilities.json")
    args = ap.parse_args()

    ratings, groups = load_ratings(Path(args.ratings))
    model = Model(ratings, groups)
    result = simulate(model, args.sims, args.seed)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))

    top = sorted(result["teams"].items(), key=lambda kv: -kv[1]["P_champion"])[:10]
    print(f"{args.sims:,} simulations (seed {args.seed}) -> {out}\n")
    print(f"{'Team':<14}{'Champion':>10}{'Final':>9}{'SemiFinal':>11}")
    for t, d in top:
        print(f"{t:<14}{d['P_champion']:>9.1%}{d['P_final']:>9.1%}{d['P_sf']:>11.1%}")
    print(f"\nExtra time in {result['extra_time_rate']:.1%} of KO ties; "
          f"penalties in {result['penalty_rate']:.1%}")


if __name__ == "__main__":
    main()
