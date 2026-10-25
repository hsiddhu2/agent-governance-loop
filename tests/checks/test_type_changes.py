"""A deploy stops when a resource would change type under the same logical id."""
from check_type_changes import type_changes


def template(**resources) -> dict:
    return {"Resources": {lid: {"Type": t} for lid, t in resources.items()}}


def test_changed_type_fails():
    live = template(Policy="AWS::IAM::Policy", Role="AWS::IAM::Role")
    new = template(Policy="AWS::IAM::ManagedPolicy", Role="AWS::IAM::Role")
    assert type_changes(new, live) == ["Policy: AWS::IAM::Policy -> AWS::IAM::ManagedPolicy"]


def test_renamed_resource_passes():
    live = template(Policy="AWS::IAM::Policy")
    new = template(ManagedPolicy="AWS::IAM::ManagedPolicy")
    assert type_changes(new, live) == []


def test_unchanged_passes():
    same = template(Role="AWS::IAM::Role")
    assert type_changes(same, same) == []
    assert type_changes({}, {}) == []
