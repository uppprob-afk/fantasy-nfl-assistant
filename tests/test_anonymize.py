from nfl_assistant.anonymize import anonymize_text, build_mapping


def test_mapping_and_replacement():
    dash = {"league": {"name": "Secret League", "id": "123456"},
            "standings": [{"roster_id": 2, "username": "bob99", "team_name": "Bob's Bombers", "nickname": "Bobby"},
                          {"roster_id": 1, "username": "al", "team_name": "al", "nickname": None}]}
    m = build_mapping(dash)
    assert m["al"] == "Manager A" and m["bob99"] == "Manager B"
    assert m["Bob's Bombers"] == "Team Bravo" and "al" in m and m["Secret League"] == "Demo League"
    text = '{"label": "Bobby (bob99)", "team": "Bob\'s Bombers", "note": "alpha al 123456", "x": "Albert"}'
    out = anonymize_text(text, m)
    assert "bob99" not in out and "Bobby" not in out and "Bombers" not in out and "123456" not in out
    assert "Nick B (Manager B)" in out
    assert "alpha Manager A" in out and "Albert" in out     # whole words only
