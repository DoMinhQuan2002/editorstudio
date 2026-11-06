from tools.beta_01_0.reconcile import classify_historical_failure


def test_post_fix_api_success_resolves_only_the_matching_historical_issue():
    assert classify_historical_failure(True, True, False) == "HISTORICAL_FAILURE_RESOLVED"


def test_unmatched_historical_failure_is_insufficient_without_current_reproduction():
    assert classify_historical_failure(True, False, False) == "POST_FIX_EVIDENCE_INSUFFICIENT"


def test_current_failure_requires_an_actual_current_reproduction():
    assert classify_historical_failure(True, False, True) == "CURRENT_FAILURE_REPRODUCED"


def test_nonfailure_case_is_not_applicable_to_failure_reconciliation():
    assert classify_historical_failure(False, False, True) == "NOT_APPLICABLE"


def test_reliability_success_does_not_mark_visual_fidelity_as_accepted():
    reliability = {"apiJobSucceeded": True, "svgSyntaxValid": True, "visibleOutputValidated": True}
    fidelity = {"status": "NOT_ESTABLISHED"}
    human = {"reviewed": False, "accepted": None, "scores": None}
    assert reliability["apiJobSucceeded"] is True
    assert fidelity["status"] != "ACCEPTED"
    assert human["reviewed"] is False and human["accepted"] is None
