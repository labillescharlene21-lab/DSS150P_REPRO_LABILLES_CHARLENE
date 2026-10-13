# Source Profile: stroke_prediction_risk

- Rows: 5110  |  Columns: 12  |  Size: 316971 bytes
- SHA-256: `644d473b05d2797006bd94865e4f8bb057f0c721617911613c82c8fcfc707420`
- Duplicate rows: 0

## Columns
| column | dtype | nulls | null % | distinct | min | max |
|---|---|---|---|---|---|---|
| id | int64 | 0 | 0.00% | 5110 | 67 | 72940 |
| gender | object | 0 | 0.00% | 3 |  |  |
| age | float64 | 0 | 0.00% | 104 | 0.08 | 82.0 |
| hypertension | int64 | 0 | 0.00% | 2 | 0 | 1 |
| heart_disease | int64 | 0 | 0.00% | 2 | 0 | 1 |
| ever_married | object | 0 | 0.00% | 2 |  |  |
| work_type | object | 0 | 0.00% | 5 |  |  |
| Residence_type | object | 0 | 0.00% | 2 |  |  |
| avg_glucose_level | float64 | 0 | 0.00% | 3979 | 55.12 | 271.74 |
| bmi | float64 | 201 | 3.93% | 418 | 10.3 | 97.6 |
| smoking_status | object | 0 | 0.00% | 4 |  |  |
| stroke | int64 | 0 | 0.00% | 2 | 0 | 1 |

## Target distribution (`stroke`)
```
stroke
0    4861
1     249
```

## Candidate unique keys: ['id']

### Categories: gender
```
gender
Female    2994
Male      2115
Other        1
```

### Categories: ever_married
```
ever_married
Yes    3353
No     1757
```

### Categories: work_type
```
work_type
Private          2925
Self-employed     819
children          687
Govt_job          657
Never_worked       22
```

### Categories: Residence_type
```
Residence_type
Urban    2596
Rural    2514
```

### Categories: smoking_status
```
smoking_status
never smoked       1892
Unknown            1544
formerly smoked     885
smokes              789
```

## Risks / notes
- TODO: leakage fields, malformed values, schema risks