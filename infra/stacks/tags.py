import aws_cdk as cdk


def apply(scope: cdk.Stack, expires: str | None) -> None:
    """Tag every resource in the stack. Refuses to synth without an expiry."""
    if not expires:
        raise ValueError(
            "Missing context value 'expires'. Pass -c expires=YYYY-MM-DD "
            "(the Makefile sets a default)."
        )
    cdk.Tags.of(scope).add("project", "agl")
    cdk.Tags.of(scope).add("env", "sandbox")
    cdk.Tags.of(scope).add("expires", expires)
