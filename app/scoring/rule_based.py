"""Deterministic, no-training-required lead scorer. Used as the scoring
fallback when no trained model is available, and as the source of pseudo-
labels for training the XGBoost model (see ml/train.py) since this demo has
no real historical conversion outcomes to learn from."""

from app.scoring.features import build_features

# Weights are calibrated against the real distribution of *valid* leads,
# where completeness barely varies (email/phone/campaign are present on
# ~100%; the incomplete ones were already filtered to invalid_leads before
# scoring). The signals that actually move are consent (~76% yes) and
# email domain (~89% free), so the score is built to separate on those:
#   corporate email + consent + campaign + phone + name  = 85  (High)
#   free email      + consent + campaign + phone + name  = 77  (High, but
#                                                              clearly below
#                                                              the corporate
#                                                              lead)
#   free email, NO consent, + campaign + phone + name    = 49  (Medium)
#   disposable/placeholder anything                       -> floored Low
# The modal lead (complete + consented + free-email) sits at 77 -- solidly
# High with headroom, not on the 70 knife-edge where a 1-point weight change
# would flip two-thirds of the population between bands. Because this
# synthetic dataset's valid leads are genuinely mostly-complete-and-
# consented, the High tier is legitimately large (~60%+); a steeper funnel
# needs more *variance* in the input data, not a heavier arbitrary penalty
# (see README Limitations).
WEIGHTS = {
    "has_first_name": 6,
    "has_last_name": 6,
    "has_email": 18,
    "has_phone": 15,
    "has_campaign_id": 12,
    "consent": 28,
    # A personal free-provider address is a real (if secondary) B2B weakness
    # signal -- enough that a corporate lead clearly outscores an otherwise-
    # identical free-email one, without single-handedly dragging the whole
    # free-email majority out of the High band (which just recreates the
    # "0% high" problem from the other direction).
    "email_is_free_provider": -8,
    # Strong enough that a disposable-email spam submission can no longer
    # outscore a real person's plain Gmail signup -- a QA audit found
    # exactly that happening (mailinator.com outscoring a genuine gmail.com
    # lead) because "not in the freemail list" was read as "looks
    # professional."
    "email_is_disposable": -55,
    "email_is_placeholder_like": -35,
    "name_is_placeholder_like": -25,
    # Less severe than the email/name placeholder penalties -- a 555
    # number is Faker's synthetic-data fingerprint, not evidence of
    # deliberate deception the way a disposable-email domain is.
    "phone_is_placeholder": -20,
}


def rule_based_score(lead) -> float:
    features = build_features(lead)
    score = sum(WEIGHTS.get(name, 0) * value for name, value in features.items())
    return max(0.0, min(100.0, score))
