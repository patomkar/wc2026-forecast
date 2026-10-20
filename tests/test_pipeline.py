"""Tests for the WC2026 forecast pipeline.

Two categories:
  1. Scoring rules must satisfy known mathematical properties (propriety,
     bounds, agreement with hand-worked examples).
  2. Data and model must be internally consistent and reproducible.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(ROOT / "forecast"))

from verify import rps, brier, log_loss, skill, murphy  # noqa: E402
import model as fc_model  # noqa: E402


# ------------------------------------------------------------------ scoring rules
def test_rps_perfect_forecast_is_zero():
    p = np.array([[1.0, 0.0, 0.0]])
    o = np.array([[1.0, 0.0, 0.0]])
    assert rps(p, o) == pytest.approx(0.0)


def test_rps_worst_forecast_is_one():
    p = np.array([[0.0, 0.0, 1.0]])
    o = np.array([[1.0, 0.0, 0.0]])
    assert rps(p, o) == pytest.approx(1.0)


def test_rps_is_distance_sensitive():
    """A draw-leaning forecast must beat an away-leaning one when home wins."""
    o = np.array([[1.0, 0.0, 0.0]])
    near = np.array([[0.0, 1.0, 0.0]])
    far = np.array([[0.0, 0.0, 1.0]])
    assert rps(near, o) < rps(far, o)


def test_rps_uniform_baseline_known_value():
    """Uniform 1/3 forecast: RPS = (1/9 + 4/9)/2 ... verified by hand."""
    p = np.array([[1 / 3, 1 / 3, 1 / 3]])
    o = np.array([[1.0, 0.0, 0.0]])
    expected = ((1 / 3 - 1) ** 2 + (2 / 3 - 1) ** 2) / 2
    assert rps(p, o) == pytest.approx(expected)


def test_scoring_rules_are_proper():
    """Reporting the true distribution must minimise expected score.

    Draws outcomes from a known p, then checks that scoring against p beats
    scoring against perturbed alternatives.
    """
    rng = np.random.default_rng(0)
    true_p = np.array([0.5, 0.3, 0.2])
    draws = rng.choice(3, size=40_000, p=true_p)
    o = np.zeros((len(draws), 3))
    o[np.arange(len(draws)), draws] = 1

    honest = np.tile(true_p, (len(draws), 1))
    for alt in ([0.6, 0.25, 0.15], [0.4, 0.35, 0.25], [0.34, 0.33, 0.33]):
        other = np.tile(alt, (len(draws), 1))
        assert rps(honest, o) < rps(other, o)
        assert brier(honest, o) < brier(other, o)
        assert log_loss(honest, o) < log_loss(other, o)


def test_skill_score_signs():
    assert skill(0.5, 1.0) == pytest.approx(0.5)   # better than reference
    assert skill(1.0, 1.0) == pytest.approx(0.0)   # equal
    assert skill(2.0, 1.0) == pytest.approx(-1.0)  # worse


def test_murphy_decomposition_reconstructs_brier():
    """reliability - resolution + uncertainty must equal the binary Brier score."""
    rng = np.random.default_rng(3)
    p = rng.random(3000)
    o = (rng.random(3000) < p).astype(float)
    bins = [(i / 10, (i + 1) / 10) for i in range(10)]
    bins[-1] = (0.9, 1.01)
    d = murphy(p, o, bins)
    direct = ((p - o) ** 2).mean()
    reconstructed = d["reliability"] - d["resolution"] + d["uncertainty"]
    assert reconstructed == pytest.approx(direct, abs=0.01)


# ------------------------------------------------------------------ data integrity
def test_results_file_has_104_matches():
    rows = list(csv.DictReader(open(ROOT / "data/results_actual.csv")))
    assert len(rows) == 104
    assert sum(1 for r in rows if r["stage"] == "GROUP") == 72


def test_every_team_plays_exactly_three_group_matches():
    from collections import Counter
    counts = Counter()
    for r in csv.DictReader(open(ROOT / "data/results_actual.csv")):
        if r["stage"] == "GROUP":
            counts[r["team_a"]] += 1
            counts[r["team_b"]] += 1
    assert len(counts) == 48
    assert set(counts.values()) == {3}


def test_ratings_and_results_use_identical_team_names():
    ratings = {r["team"] for r in csv.DictReader(open(ROOT / "data/ratings_20260610.csv"))}
    played = set()
    for r in csv.DictReader(open(ROOT / "data/results_actual.csv")):
        played.add(r["team_a"])
        played.add(r["team_b"])
    assert ratings == played, f"mismatch: {ratings ^ played}"


def test_twelve_groups_of_four():
    from collections import defaultdict
    groups = defaultdict(set)
    for r in csv.DictReader(open(ROOT / "data/ratings_20260610.csv")):
        groups[r["group"]].add(r["team"])
    assert len(groups) == 12
    assert all(len(v) == 4 for v in groups.values())


# ------------------------------------------------------------------ model
def test_match_probabilities_sum_to_one():
    ratings, groups = fc_model.load_ratings(ROOT / "data/ratings_20260610.csv")
    m = fc_model.Model(ratings, groups)
    p = m.outcome_probs("Spain", "Haiti")
    assert p["win"] + p["draw"] + p["loss"] == pytest.approx(1.0, abs=1e-6)


def test_stronger_team_is_favoured():
    ratings, groups = fc_model.load_ratings(ROOT / "data/ratings_20260610.csv")
    m = fc_model.Model(ratings, groups)
    assert m.outcome_probs("Spain", "Haiti")["win"] > 0.7
    assert m.outcome_probs("Haiti", "Spain")["win"] < 0.15


def test_model_is_symmetric_under_team_swap():
    ratings, groups = fc_model.load_ratings(ROOT / "data/ratings_20260610.csv")
    m = fc_model.Model(ratings, groups)
    ab = m.outcome_probs("France", "Norway")
    ba = m.outcome_probs("Norway", "France")
    assert ab["win"] == pytest.approx(ba["loss"], abs=1e-9)
    assert ab["draw"] == pytest.approx(ba["draw"], abs=1e-9)


def test_host_bonus_decays_in_knockouts():
    ratings, groups = fc_model.load_ratings(ROOT / "data/ratings_20260610.csv")
    m = fc_model.Model(ratings, groups)
    assert m.effective("Mexico", knockout=False) > m.effective("Mexico", knockout=True)
    # a non-host is unaffected
    assert m.effective("Spain", False) == pytest.approx(m.effective("Spain", True))


def test_simulation_is_seed_reproducible():
    ratings, groups = fc_model.load_ratings(ROOT / "data/ratings_20260610.csv")
    m = fc_model.Model(ratings, groups)
    a = fc_model.simulate(m, 400, seed=7)
    b = fc_model.simulate(m, 400, seed=7)
    assert a["teams"]["Spain"] == b["teams"]["Spain"]


def test_probabilities_are_coherent_across_stages():
    """P(champion) <= P(final) <= P(sf) <= ... for every team."""
    path = ROOT / "forecast/output/probabilities.json"
    if not path.exists():
        pytest.skip("run forecast/model.py first")
    teams = json.loads(path.read_text())["teams"]
    for name, d in teams.items():
        chain = [d["P_qualify"], d["P_r32"], d["P_r16"],
                 d["P_qf"], d["P_sf"], d["P_final"], d["P_champion"]]
        for earlier, later in zip(chain, chain[1:]):
            assert later <= earlier + 1e-9, f"{name}: {later} > {earlier}"


def test_champion_probabilities_sum_to_one():
    path = ROOT / "forecast/output/probabilities.json"
    if not path.exists():
        pytest.skip("run forecast/model.py first")
    teams = json.loads(path.read_text())["teams"]
    assert sum(d["P_champion"] for d in teams.values()) == pytest.approx(1.0, abs=0.01)


def test_prereg_verify_passes():
    r = subprocess.run([sys.executable, "scripts/prereg.py", "verify", "--event", "WC2026"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
