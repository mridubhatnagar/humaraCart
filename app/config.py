"""Demo configuration: the single seeded household.

No invite flow in V1 — the two demo phones are wired in here. Set the phone
numbers to the two Androids joined to the Twilio WhatsApp sandbox (E.164, e.g.
"+919812345678"). Names are placeholders and change nothing but display text.
"""

from __future__ import annotations

import os

from app.models import Household, Member

HOUSEHOLD_ID = "priya_household"

# The two demo phones. Override via env so you don't commit real numbers.
ACCOUNT_HOLDER_PHONE = os.getenv("HC_HOLDER_PHONE", "+910000000001")
MEMBER_PHONE = os.getenv("HC_MEMBER_PHONE", "+910000000002")


def seed_household() -> Household:
    return Household(
        id=HOUSEHOLD_ID,
        members=[
            Member("Priya", ACCOUNT_HOLDER_PHONE, is_account_holder=True),
            Member("Rahul", MEMBER_PHONE),
        ],
    )
