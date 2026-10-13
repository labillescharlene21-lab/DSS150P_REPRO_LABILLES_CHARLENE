-- Model-ready view: the 13 features plus the target, in original file order.
CREATE OR REPLACE VIEW v_model_input AS
SELECT id, source_row_seq, stroke,
       age, age_score_risk, avg_glucose_level, glucose_score_risk, bmi, bmi_score_risk,
       hypertension, heart_disease, gender_score_risk, smoking_score_risk,
       residence_score_risk, vaaf, tgi
FROM curated_stroke
ORDER BY source_row_seq;