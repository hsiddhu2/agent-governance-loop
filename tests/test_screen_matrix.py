"""How the screen matrix reads each call and sorts each field."""
from screen_matrix import EXPECTED, classify, decision, screens_on, withheld_by


def test_screens_and_their_categories_come_from_the_templates():
    screens = screens_on("get_claim_record")
    assert "US_SOCIAL_SECURITY_NUMBER" in screens["ops_screen_government_ids"]
    assert "EMAIL" in screens["ops_screen_contact_details"]
    assert all(name.startswith("ops_screen_") for name in screens)


def test_every_probe_field_has_an_expectation():
    from synthetic import probes
    assert {p["pk"].removeprefix("probe#") for p in probes()} == set(EXPECTED)


def test_a_withheld_response_names_its_screens_without_the_suffix():
    body = {"error": {"code": -32002, "message": "Output blocked by policy: Policy evaluation denied "
                      "due to ops_screen_government_ids-1ylf7yzw40, ops_screen_financial-8g330k10ot"}}
    assert withheld_by(403, body) == ["ops_screen_financial", "ops_screen_government_ids"]
    assert withheld_by(200, {"result": {}}) == []


def test_a_log_only_match_is_read_but_a_mismatch_is_not():
    span = {"attributes": {
        "aws.agentcore.policy.log_only_matched_policies": ["ops_screen_contact_details-q39ju9cfqs"],
        "aws.agentcore.policy.mismatched_policies": ["ops_screen_financial-8g330k10ot"],
        "aws.agentcore.policy.log_only_matched_policies.guardrails.sensitiveInformation.scores":
            [["ops_screen_contact_details-q39ju9cfqs", "EMAIL", "1.0000"]],
    }}
    assert decision([span]) == {"matched": ["ops_screen_contact_details"], "detected": ["EMAIL"]}


def run(matched=(), withheld=()):
    return {"matched": list(matched), "withheldBy": list(withheld)}


def test_classify():
    gov, contact = ["ops_screen_government_ids"], ["ops_screen_contact_details"]
    assert classify("US_SOCIAL_SECURITY_NUMBER", gov, [run(withheld=gov)] * 3) == "caught, withheld 3/3"
    assert classify("EMAIL", contact, [run(matched=contact)] * 3) == "caught in LOG_ONLY 3/3"
    assert classify("NAME", contact, [run(matched=contact), run(), run()]) == "missed 2/3"
    assert classify(None, [], [run()] * 3) == "no category exists"
    assert classify(None, [], [run(matched=contact), run(), run()]) == \
        "no category exists, other screen matched 1/3"
