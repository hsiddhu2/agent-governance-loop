import aws_cdk as cdk
from constructs import IConstruct


def acknowledge(scope: IConstruct, findings: dict[str, str]) -> None:
    """Accept AWS Solutions rule findings on `scope`, each with the reason it stands.

    Keys are finding ids as `make check` prints them, without the pack prefix,
    for example `AwsSolutions-IAM5[Resource::*]`. Every finding needs its own entry.
    """
    cdk.Validations.of(scope).acknowledge(*[
        cdk.Acknowledgment(id=f"AwsSolutions::{finding}", reason=reason)
        for finding, reason in findings.items()
    ])
