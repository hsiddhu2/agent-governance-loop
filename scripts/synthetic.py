"""Synthetic claim records shaped like a life insurer's: a policyholder statement and a
health statement for every claim, plus probe records that each carry one kind of field.

Every value is fictional and generated from a fixed seed, so a run is reproducible.
Values are drawn from ranges that cannot belong to a person:
  - Social Security numbers use area 666, which SSA does not assign
    (https://www.ssa.gov/employer/randomizationfaqs.html).
  - Telephone numbers use 555-0100 to 555-0199, set aside for fictional use.
  - Email addresses use example.com, reserved by RFC 2606.
  - Card numbers are the public test numbers payment processors publish.
Names, addresses and health details are generated combinations and describe nobody.
"""
import random
from datetime import date, timedelta

STATUSES = ("open", "in_review", "closed")
CLAIM_TYPES = ("death_benefit", "accelerated_benefit", "waiver_of_premium")
FIRST = ("Avery", "Jordan", "Morgan", "Riley", "Casey", "Quinn", "Taylor", "Rowan", "Emerson", "Hayden")
LAST = ("Lindqvist", "Okafor", "Marchetti", "Delgado", "Whitcombe", "Nakamura", "Brennan", "Ostrowski")
STREETS = ("Maple", "Juniper", "Harbor", "Prairie", "Cedar Ridge", "Willow Bend", "Foxglove")
CITIES = (("Springfield", "IL"), ("Madison", "WI"), ("Columbus", "OH"), ("Boise", "ID"), ("Salem", "OR"))
AREA_CODES = ("217", "608", "614", "208", "503")
TEST_CARDS = ("4111 1111 1111 1111", "5555 5555 5555 4444", "3782 822463 10005")
DOMAIN = "example.com"
DIAGNOSES = (
    ("Acute myocardial infarction, unspecified", "I21.9"),
    ("Malignant neoplasm of unspecified part of bronchus or lung", "C34.90"),
    ("Type 2 diabetes mellitus without complications", "E11.9"),
    ("Chronic obstructive pulmonary disease, unspecified", "J44.9"),
    ("Major depressive disorder, single episode, unspecified", "F32.9"),
)
MEDICATIONS = ("metformin 500 mg twice daily", "lisinopril 10 mg daily", "atorvastatin 40 mg daily",
               "sertraline 50 mg daily", "albuterol inhaler as needed", "apixaban 5 mg twice daily")
CLAIMS = 50


def _us_date(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def policyholder(rng: random.Random) -> dict:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    city, state = rng.choice(CITIES)
    born = date(1940, 1, 1) + timedelta(days=rng.randint(0, 35 * 365))
    return {
        "name": f"{first} {last}",
        "date_of_birth": _us_date(born),
        "ssn": f"666-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}",
        "address": f"{rng.randint(100, 9899)} {rng.choice(STREETS)} St, {city}, {state} "
                   f"{rng.randint(10000, 99999)}",
        "phone": f"({rng.choice(AREA_CODES)}) 555-01{rng.randint(0, 99):02d}",
        "email": f"{first}.{last}{rng.randint(1, 99)}@{DOMAIN}".lower(),
        "driver_license": f"{last[0]}{rng.randint(100, 999)}-{rng.randint(1000, 9999)}-"
                          f"{rng.randint(1000, 9999)}",
        "passport": f"{rng.randint(100000000, 999999999)}",
        "bank_account": f"{rng.randint(10**9, 10**10 - 1)}",
        "bank_routing": "011000015",
        "card": rng.choice(TEST_CARDS),
    }


def health(rng: random.Random) -> dict:
    diagnosis, icd10 = rng.choice(DIAGNOSES)
    admitted = date(2020, 1, 1) + timedelta(days=rng.randint(0, 1500))
    return {
        "medical_record_number": f"MRN-{rng.randint(10**7, 10**8 - 1)}",
        "health_plan_member_id": f"XJH{rng.randint(10**8, 10**9 - 1)}",
        "attending_physician": f"Dr. {rng.choice(FIRST)} {rng.choice(LAST)}",
        "diagnosis": diagnosis,
        "icd10": icd10,
        "medications": ", ".join(rng.sample(MEDICATIONS, 2)),
        "admitted": _us_date(admitted),
        "discharged": _us_date(admitted + timedelta(days=rng.randint(1, 21))),
        "clinical_note": f"Patient presented with symptoms consistent with {diagnosis.lower()}. "
                         f"Treated and monitored. Follow-up with {rng.choice(LAST)} cardiology clinic.",
    }


def claims() -> list[dict]:
    rng = random.Random(341)
    return [{
        "pk": f"claim#{i}",
        "policy_number": f"TEST-POL-{i:05d}",
        "status": STATUSES[i % len(STATUSES)],
        "claim_type": CLAIM_TYPES[i % len(CLAIM_TYPES)],
        "amount": 1000 + 250 * i,
        "policyholder": policyholder(rng),
        "health": health(rng),
    } for i in range(CLAIMS)]


def probes() -> list[dict]:
    """One record per kind of field, with nothing else that a detector could flag.

    Each probe holds a single field from a full record, so a guardrail that fires on it
    fired on that field. The other statement reads "No statement on file."
    """
    full = claims()[0]
    rows = []
    for side in ("policyholder", "health"):
        for field, value in full[side].items():
            rows.append({
                "pk": f"probe#{field}",
                "policy_number": "TEST-POL-PROBE",
                "status": "open",
                "claim_type": "probe",
                "amount": 0,
                "policyholder": {field: value} if side == "policyholder" else {},
                "health": {field: value} if side == "health" else {},
            })
    return rows
