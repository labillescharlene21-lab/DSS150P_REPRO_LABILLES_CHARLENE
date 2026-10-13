# Baseline vs reproduced results (auto-generated)

Run: `final-2` | status: **fail** | tolerance: 0.001

| Quantity | Baseline (expected) | Reproduced (actual) | Result |
|---|---:|---:|---|
| ROC-AUC (primary) | 0.7500 | 0.74183 | diff 0.008165, within tolerance: False |
| Train rows | 2612 | 2612 | match |
| Test rows | 653 | 653 | match |
| Test positives | 63 | 63 | match |
| scale_pos_weight | 12.2849 | 12.2849 | match |
| Train ids SHA-256 | `76114297b55cb63d...` | `76114297b55cb63d...` | match |
| Test ids SHA-256 | `65394bd0562ee1b8...` | `65394bd0562ee1b8...` | match |

## Missed stroke cases (false negatives) by threshold

| Threshold | Baseline | Reproduced | Result |
|---:|---:|---:|---|
| 0.05 | 0 | 0 | match |
| 0.075 | 1 | 1 | match |
| 0.2 | 6 | 6 | match |
| 0.35 | 9 | 11 | DIFFERENT |
| 0.4 | 12 | 13 | DIFFERENT |
| 0.45 | 17 | 17 | match |
| 0.5 | 21 | 20 | DIFFERENT |

## Environment

- xgboost 3.4.1, scikit-learn 1.9.1, Python 3.12.4, Windows-10-10.0.19045-SP0
- Hyperparameters: `{"n_estimators": 250, "learning_rate": 0.02, "max_depth": 2, "subsample": 0.7, "colsample_bytree": 0.7, "eval_metric": "logloss", "scale_pos_weight": 12.284883720930232, "random_state": 42}`
