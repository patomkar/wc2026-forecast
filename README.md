# World Cup 2026 — A Pre-Registered Probabilistic Forecast, Scored

A Monte Carlo forecast of the 2026 FIFA World Cup, frozen before the opening match and then evaluated against the outcome using standard forecast-verification metrics.

The model called the champion. **That is the least interesting thing in this repository.** A 20.4% forecast coming true is roughly what a well-calibrated model looks like one time in five and what a lucky model looks like some of the time too. The interesting part is [`MODEL_EVALUATION.md`](MODEL_EVALUATION.md), where the same forecast is scored properly and two systematic flaws are identified.

---

## Results at a glance

| Metric | Model | Benchmark | Skill |
|---|---|---|---|
| **RPS** (72 group matches) | **0.1618** | 0.2315 uniform | **+30.1%** |
| RPS vs climatology | 0.1618 | 0.2259 | +28.4% |
| Log loss | 0.8927 | 1.0986 | +18.7% |
| Multiclass Brier | 0.5240 | 0.6667 | +21.4% |
| Hit rate | 62.5% | 43.1% | +19.4pp |
| **Advancement Brier** (48 teams × 7 stages) | **0.0795** | 0.1297 base rate | **+38.7%** |
| Champion log score | 1.588 | 1.808 market | beat market by 0.220 nats |

Bootstrap 95% CI on RPS: [0.144, 0.181]. Improvement over uniform: 0.070, 95% CI [0.044, 0.095], P(>0) = 1.000.

What it got right: champion (Spain, 20.4% — the highest assigned), both finalists, **all four semifinalists** (the four highest pre-tournament semifinal probabilities were exactly the four teams that got there), 10/12 group winners, Golden Boot and Golden Glove top picks.

What it got wrong: **4/8 quarterfinalists**, Uruguay at 77% to qualify (eliminated), a 17.5% under-prediction of total goals, and systematic under-confidence across every calibration bin.

---

## Read this before quoting the RPS

Published football models cluster around **RPS 0.19–0.21** on domestic leagues. Our 0.1618 is lower. **This is not evidence of beating the literature.** World Cup groups contain fixtures like Germany 7–1 Curaçao that a domestic league filters out, and lopsided fixtures are mechanically easy to forecast. The comparable claim is the *skill score against benchmarks computed on the same fixtures*, not the raw RPS. This caveat is in the evaluation document too, because it is the single easiest way to misread this project.

---

## Pre-registration

A forecast is only falsifiable if a third party can confirm it existed, unchanged, before the event. `scripts/prereg.py` writes a manifest of SHA-256 hashes over the frozen inputs and outputs; committing it produces a timestamped, tamper-evident record. CI re-verifies those hashes on every push.

```bash
python scripts/prereg.py freeze --event WC2026 --deadline 2026-06-11T15:00:00Z
python scripts/prereg.py verify --event WC2026
```

**Honest disclosure:** the WC2026 manifest was generated *after* the tournament, and the tool says so — it stamps `frozen before: False` against the deadline. The forecast content itself was produced on 10 June 2026, before the opening match, but the cryptographic chain of custody was not established at that time, so on this event you are trusting the author rather than the hashes. The tooling exists so that future forecasts do not require that trust. Do not read the WC2026 manifest as proof of anything except artifact integrity since August 2026.

---

## Reproduce

```bash
pip install -r requirements.txt

python forecast/model.py --sims 100000       # ~4 min, seed-reproducible
python evaluation/verify.py                  # all metrics + bootstrap
python -m pytest tests/ -q                   # 19 tests
```

The model is deterministic given `--seed`. Re-running reproduces the frozen probabilities to Monte Carlo precision (Spain 20.4%, Argentina 12.3%, France 12.1%).

---

## Method

**Ratings → Poisson → Monte Carlo.**

1. **Ratings** (`data/ratings_20260610.csv`) blend an Elo-style strength measure (~45%), betting-market implied strength (~35%), and explicit adjustments for injuries, June friendly form, and host effects (~20%). Rating gaps are compressed by 0.72 toward the mean so simulated title-probability dispersion matches market dispersion. *This shrinkage turned out to be too aggressive — see evaluation §5.*
2. **Match model** converts a rating gap into two Poisson means (195 rating points ≈ 1.0 expected goal difference, baseline 1.25 goals/team).
3. **Tournament simulation** runs 100,000 complete tournaments: 72 group matches, third-place ranking, the full 32-team knockout bracket per FIFA's published slot structure, extra time at one-third scoring intensity, and shootouts as near-coinflips.

Full specification, including the sensitivity analysis, is in [`forecast/FROZEN_FORECAST.md`](forecast/FROZEN_FORECAST.md).

---

## Layout

```
data/
  ratings_20260610.csv     frozen model inputs, with sources
  results_actual.csv       all 104 match results
forecast/
  model.py                 ratings → Poisson → 100k Monte Carlo
  FROZEN_FORECAST.md       the pre-tournament forecast, unedited
  output/probabilities.json
evaluation/
  verify.py                RPS, Brier, Murphy decomposition, bootstrap
  metrics.json
scripts/
  prereg.py                hash-based pre-registration
  build_results.py         regenerates the results dataset from source
tests/                     19 tests: scoring-rule properties + data integrity
prereg/WC2026.manifest.json
```

Tests cover the mathematical properties the scoring rules must satisfy — propriety (honest reporting minimises expected score), distance-sensitivity, and that the Murphy decomposition reconstructs the Brier score — not just that the code runs.

---

## Known limitations

**n = 1.** A single tournament cannot establish forecasting skill. Everything here is one observation.

**No out-of-sample backtest.** Ratings were assembled by hand for one event. There is no held-out validation and no evidence the pipeline generalises. This is the largest gap between this project and a publishable result.

**Market contamination.** ~35% of each rating came from betting odds, so "beating the market" reflects a 4-point deviation on one team that happened to be right — not a demonstration of market inefficiency.

**Poisson is misspecified.** Observed variance/mean for goals was 1.44; Poisson requires 1.00.

**Post-hoc metric selection.** Metrics were chosen after results were known. They are the field-standard ones, but the temperature diagnostic in particular is fit on the evaluation sample and is reported as a diagnostic only — it is not applied to any headline number.

Full treatment in [`MODEL_EVALUATION.md`](MODEL_EVALUATION.md) §7.

---

## References

- Epstein (1969), *A scoring system for probability forecasts of ranked categories*, J. Appl. Meteorology
- Murphy (1973), *A new vector partition of the probability score*, J. Appl. Meteorology
- Constantinou & Fenton (2012), *Solving the problem of inadequate scoring rules for assessing probabilistic football forecast models*, JQAS 8(1)
- Constantinou (2018), *Dolores: a model that predicts football match outcomes from all over the world*, Machine Learning
- Wheatcroft (2021), *Evaluating probabilistic forecasts of football matches: the case against the ranked probability score*, JQAS
- Gneiting & Raftery (2007), *Strictly proper scoring rules, prediction, and estimation*, JASA

## License

MIT (code) · CC BY 4.0 (data and written analysis)
