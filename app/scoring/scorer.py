"""Lead scoring entrypoint used by the pipeline.

Production scoring is the transparent rule engine (app/scoring/rule_based.py):
a clamped linear combination of named quality signals. It's exact,
interpretable (every point decomposes into a signal the diagnosis text can
name), consistent run-to-run, and -- critically -- it uses the full 0-100
range on real data.

Why not the XGBoost model, given the project trains one? Because that model
is trained to approximate this very rule engine (its labels ARE the
rule-based scores -- there are no real conversion outcomes yet), and a
gradient-boosted tree ensemble structurally compresses the range of a
linear target: shallow trees average toward the population mean, deep trees
overfit the zero-signal features (created_hour, source). A pre-demo
calibration pass measured the consequence directly -- the model reproduced
the rule engine's scores to within ~1 point on held-out *synthetic* data
(validation MAE ~1.2) yet missed *real* leads by ~21 points and never
predicted above ~56, so 0% of leads reached the 70+ "high-quality" band
even though ~two-thirds genuinely qualified. Approximating a known
deterministic linear rule with a tree ensemble is the wrong tool, and no
hyperparameter setting fixed it without trading compression for
overfitting.

So the rule engine is what scores leads. The XGBoost model is still trained
and tracked in MLflow (see ml/train.py) -- but as the drop-in learning path
for when real conversion outcomes accumulate, at which point it will be
predicting something the rule engine can't (actual conversion), not just
re-deriving the rule engine. `USE_MODEL` flips it into the serving path for
experimentation; it's off by default precisely because of the compression
above.
"""

import os
from pathlib import Path

import joblib

from app.scoring.features import build_features, features_to_vector
from app.scoring.rule_based import rule_based_score

MODEL_PATH = Path(__file__).resolve().parents[2] / "ml" / "models" / "lead_scorer.joblib"
USE_MODEL = os.getenv("USE_XGBOOST_SCORER", "").lower() in ("1", "true", "yes")


class LeadScorer:
    def __init__(self):
        self._model = None
        if USE_MODEL and MODEL_PATH.exists():
            try:
                self._model = joblib.load(MODEL_PATH)
            except Exception:
                self._model = None

    def score(self, lead) -> float:
        if self._model is None:
            return rule_based_score(lead)
        try:
            vector = features_to_vector(build_features(lead))
            return max(0.0, min(100.0, float(self._model.predict([vector])[0])))
        except Exception:
            return rule_based_score(lead)

    def score_batch(self, leads: list) -> list:
        if not leads:
            return leads
        if self._model is not None:
            # One matrix, one predict() call -- calling predict() per-row in
            # a loop was measured taking 3.5s for 25k leads purely from
            # per-call overhead.
            try:
                vectors = [features_to_vector(build_features(lead)) for lead in leads]
                predictions = self._model.predict(vectors)
                for lead, predicted in zip(leads, predictions):
                    lead.quality_score = round(max(0.0, min(100.0, float(predicted))), 2)
                return leads
            except Exception:
                pass  # fall through to the rule engine
        for lead in leads:
            lead.quality_score = round(rule_based_score(lead), 2)
        return leads
