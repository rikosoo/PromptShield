from app.policy_engine import PolicySpec, Subject, evaluate


def P(**kw):
    base = {"id": "1", "name": "p", "action": "block", "mode": "enforce", "match": {"categories": ["segredo"]}}
    return PolicySpec(**{**base, **kw})


CATS = [{"id": "segredo", "confidence": 0.97}]


def test_monitor_never_changes_decision_but_records_would_decide():
    ev = evaluate([P(mode="monitor")], Subject(), CATS, 60)
    assert (ev.decision, ev.would_decide) == ("allow", "block") and len(ev.hits) == 1


def test_strongest_enforced_action_wins():
    ev = evaluate([P(action="mask", id="a", match={"categories": ["segredo"]}), P(action="block", id="b")], Subject(), CATS, 60)
    assert ev.decision == "block"


def test_scope_and_disabled_and_confidence():
    assert evaluate([P(scope={"departments": ["RH"]})], Subject(department="TI"), CATS, 60).decision == "allow"
    assert evaluate([P(scope={"apps": ["claude_code"]})], Subject(app="claude_code"), CATS, 60).decision == "block"
    assert evaluate([P(scope={"groups": ["devs"]})], Subject(groups=("ops",)), CATS, 60).decision == "allow"
    assert evaluate([P(enabled=False)], Subject(), CATS, 60).decision == "allow"
    assert evaluate([P()], Subject(), [{"id": "segredo", "confidence": 0.3}], 60).decision == "allow"


def test_min_score_only_policy():
    p = P(match={"min_score": 70}, action="ask_justification")
    assert evaluate([p], Subject(), CATS, 69).decision == "allow"
    assert evaluate([p], Subject(), CATS, 70).decision == "ask_justification"
