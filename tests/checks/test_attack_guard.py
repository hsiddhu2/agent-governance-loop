"""A scenario that targets a destructive tool runs under LOG_ONLY only when confirmed, in either mode."""
import pytest

from attack import DIRECT_CALLS, needs_confirmation


@pytest.mark.parametrize("scenario", ["claims-cleanup", "ticket-injection"])
def test_a_purge_scenario_under_log_only_needs_confirmation(scenario):
    assert needs_confirmation(scenario, "LOG_ONLY", None)
    assert not needs_confirmation(scenario, "LOG_ONLY", "purge")


@pytest.mark.parametrize("scenario", sorted(DIRECT_CALLS))
def test_nothing_needs_confirmation_while_the_gateway_enforces(scenario):
    assert not needs_confirmation(scenario, "ENFORCE", None)


def test_a_read_scenario_never_needs_confirmation():
    assert not needs_confirmation("claim-file", "LOG_ONLY", None)
