"""`ConversationService` — decides whether an inbound message belongs to
onboarding or to the agent.

Onboarding gets first refusal: unknown senders, invite links, and the one-time
address pick are all its business. Only once someone is fully set up does the
message reach the agent. Keeping the branch here means neither service has to
know the other exists, and the router stays thin.
"""

from __future__ import annotations

from app.accounts.dao import IAccountDAO
from app.core.locks import IGroupLock
from app.groups.dao import IGroupAccountDAO, IGroupDAO
from app.onboarding.service import OnboardingService
from app.whatsapp.messenger import IMessenger


HELP_TEXT = """HumaraCart — a shared Instamart cart for your household.

Just talk normally:
  add milk           search and add to the cart
  add 2 chips        quantities work too
  remove milk        take something off
  show cart          what is in the cart, and what it costs

Commands:
  checkout   place the order (account holder only)
  invite     get a link to add a flatmate (account holder only)
  help       this message

If you are not the account holder, asking to check out nudges them instead.
When I ask you to pick something, just reply with the number."""


class ConversationService:
    def __init__(
        self,
        onboarding: OnboardingService,
        agent_assembler,
        group_dao: IGroupDAO,
        group_account_dao: IGroupAccountDAO,
        messenger: IMessenger,
        account_dao: IAccountDAO,
        group_lock: IGroupLock,
    ) -> None:
        self._account_dao = account_dao
        self._onboarding = onboarding
        self._agent_assembler = agent_assembler
        self._group_dao = group_dao
        self._group_account_dao = group_account_dao
        self._messenger = messenger
        # Background tasks run on a thread pool: two inbound messages can
        # reach the agent at the same moment and race on its shared LangGraph
        # checkpoint. A per-group lock serializes agent turns for the same
        # household so that never happens, without blocking unrelated ones.
        self._group_lock = group_lock

    def handle(self, sender: str, body: str, profile_name: str | None = None) -> None:
        if profile_name:
            self._remember_name(sender, profile_name)

        if body.strip().lower() == "help":
            # Answered here rather than by the agent: it is fixed text, so
            # there is no reason to spend an LLM call or risk the model
            # inventing commands that do not exist.
            self._messenger.send(sender, HELP_TEXT)
            return

        if self._onboarding.handle_message(sender, body):
            return

        memberships = self._group_account_dao.get_by_account(sender)
        if not memberships:
            self._messenger.send(sender, "You are not part of a household yet.")
            return

        group = self._group_dao.get_by_id(memberships[0].group_id)
        if group is None or group.address_id is None:
            self._messenger.send(
                sender, "This household has no delivery address set yet."
            )
            return

        agent = self._agent_assembler.for_group(group.group_id, sender)
        if agent is None:
            self._messenger.send(
                sender,
                "The account holder needs to link their Instamart account first.",
            )
            return

        with self._group_lock.acquire(group.group_id):
            agent.handle(sender, body, group.group_id, group.address_id)

    def _remember_name(self, phone: str, profile_name: str) -> None:
        """Fill in a name we do not have yet.

        Members who join by invite arrive with no name, so attribution falls
        back to their phone number — "added by +9198…" rather than "added by
        Rahul". An existing name is left alone: it may have been set
        deliberately, and WhatsApp display names change on a whim.
        """
        account = self._account_dao.get_by_phone(phone)
        if account is not None and not account.name:
            account.name = profile_name
            self._account_dao.update(account)
