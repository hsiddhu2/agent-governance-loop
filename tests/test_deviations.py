"""An acknowledged finding must be disclosed, and a disclosure must still be needed."""
import json

from check_deviations import acknowledged_rules, disclosed_rules, problems

README = """# x

## Deviations from production

| Rule | Why |
|---|---|
| `AwsSolutions-DDB3` | synthetic rows |

## License
`AwsSolutions-IAM5` outside the section does not count.
"""


def test_reads_rules_from_synth_metadata(tmp_path):
    (tmp_path / "S.metadata.json").write_text(json.dumps({"/S/T": [
        {"type": "aws:cdk:acknowledged-rules",
         "data": {"AwsSolutions::AwsSolutions-IAM5[Resource::*]": "r",
                  "NIST.800.53.R5::NIST.800.53.R5-IAMNoInlinePolicy": "r"}},
        {"type": "aws:cdk:logicalId", "data": "T"},
    ]}))
    assert acknowledged_rules(tmp_path) == {"AwsSolutions-IAM5", "NIST.800.53.R5-IAMNoInlinePolicy"}


def test_only_the_deviations_section_counts():
    assert disclosed_rules(README) == {"AwsSolutions-DDB3"}


def test_undisclosed_and_stale_rules_both_fail():
    found = problems({"AwsSolutions-IAM5"}, {"AwsSolutions-DDB3"})
    assert len(found) == 2
    assert "AwsSolutions-IAM5" in found[0]
    assert "AwsSolutions-DDB3" in found[1]


def test_matching_sets_pass():
    assert problems({"AwsSolutions-DDB3"}, {"AwsSolutions-DDB3"}) == []
