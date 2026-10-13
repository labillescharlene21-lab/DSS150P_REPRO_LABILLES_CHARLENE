# Diagnosis: what moves the metric? (auto-generated)

Baseline AUC (paper/notebook): **0.75** | reproduced control: **0.74183** | tolerance: 0.001

## Step 1: is it the data?

- curated_rows: **3265**
- identical_to_group_engineered_file: **True**
- test_ids_match_baseline_hash: **True**

## Step 2: change one factor at a time

| Factor | Change | AUC | Delta vs control | Exceeds tolerance |
|---|---|---:|---:|:---:|
| control | Reproduced configuration (seed 42, notebook split, notebook hyperparameters) | 0.74183 | +0.00000 | no |
| seed | model random_state 7 (split unchanged) | 0.74124 | -0.00059 | no |
| seed | split random_state 7 (model seed unchanged) | 0.76495 | +0.02311 | yes |
| split | final split stratified by target (baseline was NOT) | 0.67431 | -0.06752 | yes |
| split | rows sorted by id before the split instead of source order | 0.76118 | +0.01935 | yes |
| preprocessing | scale_pos_weight from the final train set instead of the earlier 0.30 split | 0.74025 | -0.00159 | yes |
| preprocessing | scale_pos_weight = 1 | 0.76166 | +0.01983 | yes |
| hyperparameters | n_estimators 183, learning_rate 0.029 (paper's Model 2 values) | 0.74318 | +0.00135 | yes |
| hyperparameters | max_depth 3 instead of 2 | 0.71945 | -0.02238 | yes |
| features | model without the two engineered features (11 features) | 0.75125 | +0.00942 | yes |

## Step 3: how much does the metric move by chance alone?

- Splitting and training with 20 different seeds (0-19 (split and model seed equal)): mean AUC **0.7612**, std **0.0377**, range **0.7015 to 0.8301**.
- Bootstrap 95% confidence interval for the reproduced AUC on the baseline test set (653 rows, 63 stroke cases): **0.6771 to 0.807**.
- Meaning: differences of a few hundredths in AUC between two configurations are within split/seed noise on this dataset. Reproducing 0.7500 therefore depends on reproducing the exact split, which the split manifest hashes verify.

## Step 4: library versions

This run: Python 3.12.4, xgboost 3.4.1, scikit-learn 1.9.1, pandas 3.0.6.

Library version cannot be varied inside one process. Measured separately: xgboost 2.1.4 to 3.2.0 give AUC 0.75087; xgboost >= 3.3.0 gives 0.75004 on identical data, split and parameters (scikit-learn 1.7.2 vs 1.8.0 made no difference).

## How to read this

1. Data identity true and split hashes matching means any metric difference is NOT the data or the split rows.
2. A factor with `exceeds tolerance = yes` must be pinned or documented, otherwise it can silently change the result.
3. A factor that changes nothing (`no`) is not the cause; move on to the next one.
4. If nothing here explains a difference, compare library versions, then platform/threads.
