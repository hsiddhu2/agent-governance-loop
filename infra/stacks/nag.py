import aws_cdk as cdk
from constructs import IConstruct


def acknowledge(scope: IConstruct, findings: dict[str, str]) -> None:
    """Accept rule findings on `scope`, each with the reason it stands.

    Keys are finding ids as `make check` prints them, for example
    `AwsSolutions-IAM5[Resource::*]` or `NIST.800.53.R5-IAMNoInlinePolicy`.
    The rule pack is the part before the first hyphen. Every finding needs its own
    entry, and every rule acknowledged anywhere must be listed in the README's
    deviations table, which scripts/check_deviations.py checks.
    """
    cdk.Validations.of(scope).acknowledge(*[
        cdk.Acknowledgment(id=f"{finding.split('-', 1)[0]}::{finding}", reason=reason)
        for finding, reason in findings.items()
    ])
