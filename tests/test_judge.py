from seo_intel.judge import action_key, cohen_kappa, fixed_checks


def test_kappa_matches_a_worked_example():
    # 20 both yes, 15 both no, 5 and 10 split
    human = ["sound"] * 25 + ["unsound"] * 25
    judge = ["sound"] * 20 + ["unsound"] * 5 + ["sound"] * 10 + ["unsound"] * 15
    assert abs(cohen_kappa(human, judge) - 0.4) < 1e-9


def test_kappa_edges():
    assert cohen_kappa(["sound"] * 4, ["sound"] * 4) == 1.0
    assert cohen_kappa([], []) == 0.0
    assert cohen_kappa(["sound", "unsound"], ["unsound", "sound"]) == -1.0


def test_fixed_checks():
    good = {"type": "merge_301", "urls": ["a", "b"], "rationale": "Merge, see [c1].",
            "claims": [{"id": "c1", "url": "a", "field": "title", "value": "T"}]}
    assert fixed_checks(good) == []
    assert action_key(good) == "merge_301|a|b"
    bad = dict(good, rationale="Overlap is 90 percent.", claims=[])
    assert fixed_checks(bad) == ["no claims", "no claim reference"]
