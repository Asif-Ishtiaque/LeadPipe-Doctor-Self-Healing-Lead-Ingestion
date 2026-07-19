"""Lead scoring entrypoint used by the pipeline. Prefers the trained
XGBoost model (ml/models/lead_scorer.joblib); if it hasn't been trained yet
or fails to load, transparently falls back to the rule-based scorer so
scoring never blocks the rest of the pipeline."""

from pathlib import Path

import joblib

from app.scoring.features import build_features, features_to_vector
from app.scoring.rule_based import rule_based_score

MODEL_PATH = Path(__file__).resolve().parents[2] / "ml" / "models" / "lead_scorer.joblib"


class LeadScorer:
    def __init__(self):
        self._model = None
        if MODEL_PATH.exists():
            try:
                self._model = joblib.load(MODEL_PATH)
            except Exception:
                self._model = None

    def score(self, lead) -> float:
        if self._model is None:
            return rule_based_score(lead)
        vector = features_to_vector(build_features(lead))
        try:
            predicted = float(self._model.predict([vector])[0])
        except Exception:
            # Most likely a stale model trained against an older
            # FEATURE_NAMES shape (e.g. a feature added/removed since it
            # was last trained) -- the docstring's promise that scoring
            # never blocks the pipeline wasn't actually enforced here
            # before; a shape mismatch would raise straight out of
            # predict() and take the whole batch down with it.
            return rule_based_score(lead)
        return max(0.0, min(100.0, predicted))

    def score_batch(self, leads: list) -> list:
        if not leads:
            return leads
        if self._model is not None:
            # One matrix, one predict() call -- calling predict() per-row
            # in a loop was measured taking 3.5s for 25k leads purely
            # from per-call overhead; XGBoost (like most sklearn-style
            # models) is built for vectorized batch prediction, not
            # one-row-at-a-time.
            vectors = [features_to_vector(build_features(lead)) for lead in leads]
            try:
                predictions = self._model.predict(vectors)
                for lead, predicted in zip(leads, predictions):
                    lead.quality_score = round(max(0.0, min(100.0, float(predicted))), 2)
                return leads
            except Exception:
                pass  # fall through to rule-based below -- see score()'s comment
        for lead in leads:
            lead.quality_score = round(rule_based_score(lead), 2)
        return leads
