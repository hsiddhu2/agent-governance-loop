"""The synthetic tickets carry what the support scenarios need, and pasted SSNs come from area 666."""
import re

from synthetic import INJECTED, PASTED, TICKETS, claims, tickets


def test_tickets_are_reproducible():
    assert tickets() == tickets()
    assert len(tickets()) == TICKETS


def test_each_ticket_names_an_existing_claim():
    known = {c["pk"] for c in claims()}
    assert all(t["claim_id"] in known for t in tickets())


def test_pasted_identifiers_are_from_reserved_ranges():
    rows = tickets()
    for i in PASTED:
        body = rows[i]["body"]
        for ssn in re.findall(r"\b\d{3}-\d{2}-\d{4}\b", body):
            assert ssn.startswith("666-")
    clean = [t for i, t in enumerate(rows) if i not in PASTED]
    assert not any(re.search(r"\b666-\d{2}-\d{4}\b", t["body"]) for t in clean)


def test_one_ticket_carries_the_injection():
    marked = [t for t in tickets() if "purge_claims" in t["body"]]
    assert [t["pk"] for t in marked] == [f"ticket#{INJECTED}"]


def test_ticket_zero_carries_no_identifier():
    # The access matrix reads ticket#0, so no screen may withhold it.
    body = tickets()[0]["body"]
    assert 0 not in PASTED and INJECTED != 0
    assert not re.search(r"\d{3}-\d{2}-\d{4}|\d{4} \d{4}", body)
