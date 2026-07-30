"""Local rehearsal CLI — drives the real `ConversationService` through
`ConsoleMessenger` instead of Twilio, so the full flow (including broadcasts)
can be rehearsed with zero Twilio spend. Still hits the real Swiggy account
via `McpInstamartClient`, same as the live bot — only the messaging transport
is swapped.

Run inside docker, against the real persistent DB used by `docker compose up app`:

  docker compose run --rm -e PYTHONPATH=/app app python scripts/local_cli.py

Commands:
  as <phone>   switch which phone number is "talking" (simulates a different sender)
  quit / exit  stop

Anything else is sent as a WhatsApp message from whichever phone is current —
replies (including broadcasts to other household members) print to the console.
"""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet

from app.accounts.dao import AccountDAO
from app.agent.factory import AgentAssembler, make_checkpointer
from app.cart.dao import ItemCartDAO
from app.conversation.service import ConversationService
from app.core.db import make_session_factory
from app.groups.dao import GroupAccountDAO, GroupDAO
from app.instamart.mcp_client import McpInstamartClient
from app.invites.dao import InviteTokenDAO
from app.onboarding.service import OnboardingService
from app.settings import get_settings
from app.whatsapp.console_messenger import ConsoleMessenger

logging.basicConfig(level=logging.INFO, format="%(message)s")


def build_conversation_service() -> ConversationService:
    settings = get_settings()
    session = make_session_factory(settings.database_url)()
    fernet = Fernet(settings.token_encryption_key.encode())
    messenger = ConsoleMessenger()

    account_dao = AccountDAO(session, fernet)
    group_dao = GroupDAO(session)
    group_account_dao = GroupAccountDAO(session)
    item_cart_dao = ItemCartDAO(session)
    invite_token_dao = InviteTokenDAO(session)

    assembler = AgentAssembler(
        settings=settings,
        account_dao=account_dao,
        group_account_dao=group_account_dao,
        item_cart_dao=item_cart_dao,
        messenger=messenger,
        checkpointer=make_checkpointer(settings.database_url),
    )
    onboarding = OnboardingService(
        account_dao=account_dao,
        group_dao=group_dao,
        group_account_dao=group_account_dao,
        invite_token_dao=invite_token_dao,
        messenger=messenger,
        settings=settings,
        pending_verifiers={},
        client_factory=McpInstamartClient,
    )
    return ConversationService(
        onboarding=onboarding,
        agent_assembler=assembler,
        group_dao=group_dao,
        group_account_dao=group_account_dao,
        messenger=messenger,
        account_dao=account_dao,
    )


def main() -> None:
    conversation = build_conversation_service()
    current = input("Phone number to start as (e.g. +918562851868): ").strip()
    print(
        f"\nTalking as {current}. Type 'as <phone>' to switch sender, 'quit' to exit.\n"
    )
    while True:
        try:
            line = input(f"[{current}] > ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit"):
            break
        if line.lower().startswith("as "):
            current = line[3:].strip()
            print(f"Now talking as {current}")
            continue
        conversation.handle(current, line)


if __name__ == "__main__":
    main()
