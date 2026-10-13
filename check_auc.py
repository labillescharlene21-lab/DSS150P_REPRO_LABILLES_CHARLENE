import pandas as pd, xgboost
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

d = pd.read_csv("data/curated/stroke_curated.csv")
f = ['age','age_score_risk','avg_glucose_level','glucose_score_risk','bmi','bmi_score_risk',
     'hypertension','heart_disease','gender_score_risk','smoking_score_risk',
     'residence_score_risk','VAAF','TGI']
X, y = d[f], d['stroke']
_, _, ytr, _ = train_test_split(X, y, test_size=0.30, random_state=42, stratify=y)
spw = (ytr == 0).sum() / (ytr == 1).sum()
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
m = XGBClassifier(n_estimators=250, learning_rate=0.02, max_depth=2, scale_pos_weight=spw,
                  subsample=0.7, colsample_bytree=0.7, eval_metric='logloss', random_state=42)
m.fit(Xtr, ytr)
print("xgboost", xgboost.__version__, "AUC %.5f" % roc_auc_score(yte, m.predict_proba(Xte)[:, 1]))