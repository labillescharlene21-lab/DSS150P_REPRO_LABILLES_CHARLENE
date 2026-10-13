"""Regenerates docs/architecture.png and docs/lineage.png.  Run:  python scripts/make_diagrams.py
(needs matplotlib; it is a documentation-only dependency, not part of the pipeline)."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

DOCS = Path(__file__).resolve().parents[1] / "docs"
C = {"task": "#cfe2ff", "data": "#d1e7dd", "db": "#ffe5b4", "gate": "#f8d7da", "out": "#e2d9f3", "src": "#fff3cd"}


def box(ax, x, y, w, h, text, kind, size=9, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=0.8",
                                fc=C[kind], ec="#444", lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size,
            fontweight="bold" if bold else "normal", linespacing=1.25)


def arrow(ax, a, b, text="", rad=0.0, size=7.5, dy=1.1):
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="-|>", lw=1.5, color="#333",
                                                    connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy, text, ha="center", va="bottom", fontsize=size, color="#222")


def architecture():
    fig, ax = plt.subplots(figsize=(20, 11.5), dpi=110)
    ax.set_xlim(0, 100); ax.set_ylim(0, 58); ax.axis("off")
    ax.text(50, 56.3, "Stroke-risk reproducible data pipeline: architecture and data movement", ha="center",
            fontsize=17, fontweight="bold")
    ax.text(50, 54.3, "Same code path from a laptop, Docker, or Airflow:  python -m src.cli <stage> --run-id <id>",
            ha="center", fontsize=10.5, color="#333")

    # orchestration / runtime band
    ax.add_patch(FancyBboxPatch((1, 47), 98, 5.2, boxstyle="round,pad=0.2", fc="#f3f3f3", ec="#888", lw=1, ls="--"))
    ax.text(2, 50.6, "Docker Compose", fontsize=10, fontweight="bold", color="#444")
    box(ax, 14, 47.7, 22, 3.6, "postgres:16\nhealthcheck gates startup", "db", 8.5)
    box(ax, 40, 47.7, 22, 3.6, "pipeline image (python 3.12)\nreproducible CLI", "task", 8.5)
    box(ax, 66, 47.7, 31, 3.6, "Airflow 3.3.1 DAG predictive_repro_pipeline\nschedule=None, retries 2 x 30 s, run_id passed to every task", "task", 8.2)

    w, h = 13.2, 6.2
    # row 1: left -> right
    r1 = 38
    xs = [2, 18, 34, 50, 66, 83]
    box(ax, xs[0], r1, w, h, "Source CSV\n5,110 rows x 12\nimmutable, SHA-256\nin source_manifest.yml", "src", 8.5)
    box(ax, xs[1], r1, w, h, "ingest_source\n3 deterministic batches\ncheckpoint + record_hash", "task", 8.5)
    box(ax, xs[2], r1, w, h, "data/raw\nbatch_001-003.csv\n+ audit columns", "data", 8.5)
    box(ax, xs[3], r1, w, h, "validate_raw\n12 checks\n(schema, checksum, hash)", "gate", 8.5)
    box(ax, xs[4], r1, w, h, "transform_staging\ntypes, cleaning, age 35-90\nquarantine bad rows", "task", 8.5)
    box(ax, xs[5], r1, 14.5, h, "data/staging\n3,265 rows\n+ data/quarantine", "data", 8.5)
    for i in range(5):
        arrow(ax, (xs[i] + w, r1 + h / 2), (xs[i + 1], r1 + h / 2))
    # row 2: right -> left
    r2 = 25
    box(ax, xs[5], r2, 14.5, h, "build_curated\n5 score columns\nVAAF, TGI", "task", 8.5)
    box(ax, xs[4], r2, w, h, "data/curated\n3,265 x 22\nsource order", "data", 8.5)
    box(ax, xs[3], r2, w, h, "load_postgres\nONE transaction\nON CONFLICT (id)", "task", 8.5)
    box(ax, xs[2], r2, w, h, "PostgreSQL\nstaging_stroke\ncurated_stroke, run log", "db", 8.5)
    box(ax, xs[1], r2, w, h, "validate_curated\n23 checks incl.\nfeature fingerprint", "gate", 8.5)
    box(ax, xs[0], r2, w, h, "train_model\nXGBoost, seed 42\nsplit manifest", "task", 8.5)
    arrow(ax, (xs[5] + 7, r1), (xs[5] + 7, r2 + h), rad=0)
    for a, b in ((5, 4), (4, 3), (3, 2), (2, 1), (1, 0)):
        x0 = xs[a] + (0 if a != 5 else 0)
        arrow(ax, (x0, r2 + h / 2), (xs[b] + w, r2 + h / 2))
    # row 3: left -> right
    r3 = 12
    box(ax, xs[0], r3, w, h, "evaluate_model\nAUC + threshold table\npredictions", "task", 8.5)
    box(ax, xs[1], r3, w, h, "reproducibility_check\nAUC vs 0.7500 +/- 0.001\nsplit ids vs baseline", "gate", 8.5)
    box(ax, xs[2], r3, w, h, "publish_outputs\ncopy data product\nrun_summary.json", "task", 8.5)
    box(ax, xs[3], r3, 29, h, "outputs/\nmetrics.json  predictions.csv  model/xgb_model.json\ncurated_stroke.csv  reproducibility_check.json", "out", 8.5)
    box(ax, 82, r3, 16.5, h, "Consumers\nrisk-screening analysts,\nPostgreSQL view v_model_input", "out", 8.5)
    arrow(ax, (xs[0] + w / 2, r2), (xs[0] + w / 2, r3 + h))
    for i in range(2):
        arrow(ax, (xs[i] + w, r3 + h / 2), (xs[i + 1], r3 + h / 2))
    arrow(ax, (xs[2] + w, r3 + h / 2), (xs[3], r3 + h / 2))
    arrow(ax, (xs[3] + 29, r3 + h / 2), (82, r3 + h / 2))

    # governance / observability
    ax.add_patch(FancyBboxPatch((1, 1), 47.5, 8.4, boxstyle="round,pad=0.2", fc="#fafafa", ec="#999"))
    ax.text(2, 8.2, "Contracts and baselines (metadata/)", fontsize=9.5, fontweight="bold")
    ax.text(2, 6.9, "source_manifest.yml  data_contract.yml  expected_metrics.json\nfeature_fingerprint.json  split_manifest.json\nconfig/settings.yml + .env (paths, seeds, hyperparameters, thresholds)",
            fontsize=8.8, va="top", linespacing=1.6)
    ax.add_patch(FancyBboxPatch((51.5, 1), 47.5, 8.4, boxstyle="round,pad=0.2", fc="#fafafa", ec="#999"))
    ax.text(52.5, 8.2, "Observability (every stage, every run)", fontsize=9.5, fontweight="bold")
    ax.text(52.5, 6.9, "logs/pipeline.jsonl : ts, run_id, stage, rows, duration, error\noutputs/run_records/<run_id>.json : status, attempts, counts per stage\noutputs/quality/*.json : 37 named checks with category and result",
            fontsize=8.8, va="top", linespacing=1.6)
    # legend
    for i, (k, lab) in enumerate([("task", "pipeline stage"), ("gate", "quality gate (stops the run)"),
                                  ("data", "data layer"), ("db", "PostgreSQL / service"), ("out", "published output")]):
        ax.add_patch(FancyBboxPatch((3 + i * 19, 45.2), 2.2, 1.3, boxstyle="round,pad=0.1", fc=C[k], ec="#444"))
        ax.text(6 + i * 19, 45.85, lab, fontsize=8.5, va="center")
    fig.savefig(DOCS / "architecture.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def elbow(ax, pts):
    ax.plot([p[0] for p in pts[:-1]], [p[1] for p in pts[:-1]], color="#333", lw=1.5)
    ax.annotate("", xy=pts[-1], xytext=pts[-2], arrowprops=dict(arrowstyle="-|>", lw=1.5, color="#333"))


def lineage():
    fig, ax = plt.subplots(figsize=(20, 14), dpi=110)
    ax.set_xlim(0, 100); ax.set_ylim(0, 72); ax.axis("off")
    ax.text(50, 70.6, "Data lineage: source fields to model features to predictions and metrics", ha="center",
            fontsize=17, fontweight="bold")
    ax.text(50, 68.6, "Boxes are data artifacts (row counts from the reference run); arrows are the transformations that produce them",
            ha="center", fontsize=10.5, color="#333")

    w, h, y1 = 19, 8, 58
    xs = [1.5, 27.5, 53.5, 79.5]
    box(ax, xs[0], y1, w, h, "SOURCE\nStroke_Prediction_Dataset.csv\n5,110 rows x 12 columns\nSHA-256 in source_manifest.yml", "src", 8.6, True)
    box(ax, xs[1], y1, w, h, "RAW  data/raw/batch_001-003.csv\n5,110 rows, all text (faithful copy)\n+ source_row_seq, record_hash,\npipeline_run_id, source_checksum", "data", 8.4)
    box(ax, xs[2], y1, w, h, "STAGING\ndata/staging/stroke_staging.csv\nPostgreSQL staging_stroke\n3,265 rows x 16 (typed)", "data", 8.6)
    box(ax, xs[3], y1, w, h, "CURATED\ndata/curated/stroke_curated.csv\nPostgreSQL curated_stroke, v_model_input\n3,265 rows x 22", "data", 8.6)
    for i, lab in enumerate(["ingest_source", "transform_staging", "build_curated"]):
        arrow(ax, (xs[i] + w, y1 + h / 2), (xs[i + 1], y1 + h / 2), lab, dy=0.6, size=8)

    box(ax, xs[2], 48.2, w, 6, "QUARANTINE\ndata/quarantine/rejected_rows.csv\n0 rows in the reference run", "data", 8.4)
    arrow(ax, (xs[2] + w / 2, y1), (xs[2] + w / 2, 54.2), "", dy=0)
    ax.text(xs[2] + w / 2 + 1, 56.0, "rows failing\nthe data contract", fontsize=7.8, va="center")
    ax.add_patch(FancyBboxPatch((1.5, 46.8), 48, 8.6, boxstyle="round,pad=0.2", fc="#fafafa", ec="#999"))
    ax.text(2.4, 54.2, "Rules applied between RAW and STAGING", fontsize=9, fontweight="bold", va="top")
    ax.text(2.4, 52.2, "1. parse types; invalid or out-of-range rows go to quarantine\n"
                       "2. gender 'Other' -> mode (1 row)    3. children with 'Unknown' smoking -> never smoked\n"
                       "4. keep age 35-90 (drops 1,845 rows)    5. impute BMI with the median 29.8 (154 rows)",
            fontsize=8.6, va="top", linespacing=1.55)

    y2 = 33
    elbow(ax, [(xs[3] + w / 2, y1), (xs[3] + w / 2, 44.6), (15, 44.6), (15, y2 + h)])
    ax.text(50, 45.2, "curated rows in source order:  13 model features + target", fontsize=8.6, ha="center")

    box(ax, 1.5, y2, 27, h, "SPLIT   80 / 20,  random_state 42, NOT stratified\nscale_pos_weight 12.2849 (from an earlier\nstratified 0.30 split)\nmetadata/split_manifest.json (id hashes)", "task", 8.4)
    box(ax, 34, y2, 14, h, "TRAIN  2,612 rows\nTEST  653 rows\n(63 stroke cases)", "data", 8.8)
    box(ax, 54, y2, 18, h, "MODEL\nXGBoost, 250 trees\nlr 0.02, depth 2\noutputs/model/xgb_model.json", "out", 8.4)
    box(ax, 78, y2, 20.5, h, "OUTPUTS\npredictions.csv (653 rows)\nmetrics.json (ROC-AUC 0.7500)\nreproducibility_check.json\nvs metadata/expected_metrics.json", "out", 8.4)
    arrow(ax, (28.5, y2 + h / 2), (34, y2 + h / 2))
    arrow(ax, (48, y2 + h / 2), (54, y2 + h / 2), "fit", dy=0.6, size=8)
    arrow(ax, (72, y2 + h / 2), (78, y2 + h / 2), "predict", dy=0.6, size=8)

    ax.text(50, 30.2, "Field-level lineage: which source column produces which curated column, and how the model uses it",
            ha="center", fontsize=12.5, fontweight="bold")
    rows = [
        ("id", "key only (unique business key, not a feature)", "-"),
        ("gender", "gender; gender_score_risk (Female 0, Male 1); 'Other' -> mode", "gender_score_risk, VAAF"),
        ("age", "age; age_score_risk (age > 54 -> 1); study scope 35-90", "age, age_score_risk, VAAF"),
        ("hypertension", "hypertension (0/1)", "hypertension, VAAF"),
        ("heart_disease", "heart_disease (0/1)", "heart_disease"),
        ("Residence_type", "residence_score_risk (Rural 1, Urban 2)", "residence_score_risk"),
        ("avg_glucose_level", "glucose_score_risk (<140: 0, 140-199: 1, >=200: 2); >=126 adds VAAF points", "avg_glucose_level, glucose_score_risk, VAAF, TGI"),
        ("bmi", "median-imputed; bmi_score_risk (>=23 -> 1); >=25 adds VAAF points", "bmi, bmi_score_risk, VAAF, TGI"),
        ("smoking_status", "smoking_score_risk (never 0, Unknown 1, former 2, smokes 3)", "smoking_score_risk, VAAF"),
        ("ever_married, work_type", "kept in staging; dropped from curated (work_type only used to fix 'children')", "-"),
        ("stroke", "target (binary)", "target; not a feature"),
        ("derived", "VAAF = table vascular age - age;   TGI = bmi x avg_glucose_level", "VAAF, TGI"),
    ]
    tbl = ax.table(cellText=rows, colLabels=["Source column", "Transformation", "Used by the model as"],
                   cellLoc="left", colLoc="left", bbox=[0.02, 0.01, 0.96, 0.385], colWidths=[0.17, 0.50, 0.29])
    tbl.auto_set_font_size(False); tbl.set_fontsize(9)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#999")
        if r == 0:
            cell.set_facecolor("#cfe2ff"); cell.set_text_props(fontweight="bold")
        elif r == len(rows):
            cell.set_facecolor("#fff3cd")
    fig.savefig(DOCS / "lineage.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    DOCS.mkdir(exist_ok=True)
    architecture(); lineage()
    print("wrote docs/architecture.png and docs/lineage.png")
