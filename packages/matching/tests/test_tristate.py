from packages.matching.tristate import TriState


def test_tristate_values() -> None:
    assert TriState.ELIGIBLE.value == "eligible"
    assert TriState.POSSIBLE.value == "possible"
    assert TriState.INELIGIBLE.value == "ineligible"
