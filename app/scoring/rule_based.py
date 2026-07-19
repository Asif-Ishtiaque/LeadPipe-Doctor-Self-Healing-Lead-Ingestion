"""Deterministic, no-training-required lead scorer. Used as the scoring
fallback when no trained model is available, and as the source of pseudo-
labels for training the XGBoost model (see ml/train.py) since this demo has
no real historical conversion outcomes to learn from."""

from app.scoring.features import build_features

WEIGHTS = {
    "has_first_name": 5,
    "has_last_name": 5,
    "has_email": 20,
    "has_phone": 20,
    "has_campaign_id": 10,
    "consent": 30,
    "email_is_free_provider": -5,
    # Strong enough that a disposable-email spam submission can no longer
    # outscore a real person's plain Gmail signup -- a QA audit found
    # exactly that happening (mailinator.com scored 50.6, a genuine
    # gmail.com lead scored 45.49) because "not in the 5-domain freemail
    # list" was being read as "looks professional."
    "email_is_disposable": -50,
    "email_is_placeholder_like": -30,
    "name_is_placeholder_like": -20,
    # Less severe than the email/name placeholder penalties -- a 555
    # number is Faker's synthetic-data fingerprint, not evidence of
    # deliberate deception the way a disposable-email domain is.
    "phone_is_placeholder": -15,
}


def rule_based_score(lead) -> float:
    features = build_features(lead)
    score = sum(WEIGHTS.get(name, 0) * value for name, value in features.items())
    return max(0.0, min(100.0, score))
