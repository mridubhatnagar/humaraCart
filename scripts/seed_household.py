#!/usr/bin/env python3
"""
Seeds the demo household straight into the DB, skipping the in-chat onboarding.

Does the Swiggy OAuth login on localhost (the proven redirect), then writes:
  Account(holder)  with the real encrypted access token
  Account(member)  with no token, as designed
  Group            with the delivery address you pick
  GroupAccount x2  holder + member

After this the agent works immediately — a WhatsApp message goes straight to
it, no onboarding flow involved.

Run inside docker, publishing the OAuth callback port so your browser can
reach it:

  docker compose run --rm -p 8765:8765 \\
    -e HC_HOLDER_PHONE=+91... -e HC_MEMBER_PHONE=+91... \\
    app python scripts/seed_household.py

The token has no refresh and expires in about 5 days, so re-run this before
recording.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cryptography.fernet import Fernet
from sqlalchemy.orm import sessionmaker

from app.accounts.dao import AccountDAO
from app.accounts.models import Account
from app.core.db import create_all, make_engine
from app.groups.dao import GroupAccountDAO, GroupDAO
from app.groups.models import Group, GroupAccount, Role
from app.instamart.mcp_client import McpInstamartClient
from app.settings import get_settings
from verify_mcp_client import get_real_bearer_token, line


def main() -> None:
    settings = get_settings()
    holder_phone = os.getenv("HC_HOLDER_PHONE")
    member_phone = os.getenv("HC_MEMBER_PHONE")
    if not holder_phone:
        print("Set HC_HOLDER_PHONE (E.164, e.g. +919812345678). Aborting.")
        sys.exit(1)

    line("Swiggy login — the holder's account")
    token = get_real_bearer_token()

    client = McpInstamartClient(token)
    addresses = client.get_addresses()
    if not addresses:
        print("No saved addresses on this account. Add one in the Instamart app first.")
        sys.exit(1)

    line("Pick the household delivery address")
    for i, a in enumerate(addresses, 1):
        print(f"  {i}. [{a.tag}] {a.line}")
    try:
        chosen = addresses[int(input("\nNumber: ").strip()) - 1]
    except (ValueError, IndexError):
        print("Invalid choice. Aborting.")
        sys.exit(1)

    engine = make_engine(settings.database_url)
    create_all(engine)
    session = sessionmaker(bind=engine)()

    account_dao = AccountDAO(session, Fernet(settings.token_encryption_key.encode()))
    group_dao = GroupDAO(session)
    group_account_dao = GroupAccountDAO(session)

    holder = account_dao.get_by_phone(holder_phone)
    if holder is None:
        account_dao.create(
            Account(phone=holder_phone, name="Priya", instamart_access_token=token)
        )
    else:
        holder.instamart_access_token = token
        account_dao.update(holder)

    if member_phone and account_dao.get_by_phone(member_phone) is None:
        account_dao.create(Account(phone=member_phone, name="Rahul"))

    existing = [
        m
        for m in group_account_dao.get_by_account(holder_phone)
        if m.role == Role.HOLDER
    ]
    if existing:
        group_id = existing[0].group_id
        group = group_dao.get_by_id(group_id)
        group.address_id = chosen.id
        group_dao.update(group)
    else:
        group_id = str(uuid.uuid4())
        group_dao.create(Group(group_id=group_id, address_id=chosen.id))
        group_account_dao.create(
            GroupAccount(group_id=group_id, account_id=holder_phone, role=Role.HOLDER)
        )

    if (
        member_phone
        and group_account_dao.get_by_group_and_account(group_id, member_phone) is None
    ):
        group_account_dao.create(
            GroupAccount(group_id=group_id, account_id=member_phone, role=Role.MEMBER)
        )

    line("Seeded")
    print("group_id  :", group_id)
    print("address   :", f"[{chosen.tag}] {chosen.line}")
    print("holder    :", holder_phone)
    print("member    :", member_phone or "(none)")
    print("db        :", settings.database_url)
    print("\nMessage the bot from either number and it goes straight to the agent.")


if __name__ == "__main__":
    main()
