"""`OnboardingService` — orchestrates account holder OAuth linking, address
selection, and the JWT invite/join flow. The one service that coordinates
`AccountDAO`, `GroupDAO`, `GroupAccountDAO`, `InviteTokenDAO`, `IInstamartClient`,
and `IMessenger` together (CLAUDE.md: a service earns its place by coordinating
≥2 collaborators with real decisions — this does).

Address-selection-pending is derived from DB state alone (holder role +
`Group.address_id IS NULL`), not a separate session flag, so it survives this
service being reconstructed per request. The PKCE `code_verifier`, by
contrast, must live in a short-lived process-wide store (injected, not
persisted) — see `pending_verifiers` — since it exists only to bridge the
few seconds between sending the authorize link and the browser's callback.
"""

from __future__ import annotations

import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt

from app.accounts.dao import IAccountDAO
from app.accounts.models import Account
from app.groups.dao import IGroupAccountDAO, IGroupDAO
from app.groups.models import Group, GroupAccount, Role
from app.instamart.client import IInstamartClient
from app.instamart.oauth import (
    build_authorize_url,
    exchange_code_for_token,
    generate_pkce_pair,
)
from app.invites.dao import IInviteTokenDAO
from app.invites.jwt_tokens import sign, verify
from app.invites.models import InviteToken
from app.settings import Settings
from app.whatsapp.messenger import IMessenger

INVITE_EXPIRY = timedelta(hours=24)
OAUTH_STATE_EXPIRY = timedelta(minutes=10)


class OnboardingService:
    def __init__(
        self,
        account_dao: IAccountDAO,
        group_dao: IGroupDAO,
        group_account_dao: IGroupAccountDAO,
        invite_token_dao: IInviteTokenDAO,
        messenger: IMessenger,
        settings: Settings,
        pending_verifiers: dict[str, str],
        client_factory: Callable[[str], IInstamartClient],
    ) -> None:
        self._account_dao = account_dao
        self._group_dao = group_dao
        self._group_account_dao = group_account_dao
        self._invite_token_dao = invite_token_dao
        self._messenger = messenger
        self._settings = settings
        self._pending_verifiers = pending_verifiers
        self._client_factory = client_factory

    def handle_message(self, sender: str, body: str) -> bool:
        """Handle anything onboarding-shaped. Returns True if this message was
        onboarding's to deal with; False means the sender is fully set up and
        the message belongs to the agent instead."""
        body = body.strip()

        if self._looks_like_invite_token(body):
            self._consume_invite(sender, body)
            return True

        if body.lower() == "invite":
            self._generate_invite(sender)
            return True

        if self._account_dao.get_by_phone(sender) is None:
            self._start_holder_onboarding(sender)
            return True

        pending_group = self._pending_address_selection_group(sender)
        if pending_group is not None:
            self._complete_address_selection(sender, pending_group, body)
            return True

        return False

    def complete_holder_oauth(self, code: str, state: str) -> None:
        """Called by the /oauth/callback route after Swiggy redirects back."""
        payload = verify(state, self._settings.jwt_secret)
        phone = payload["phone"]
        verifier = self._pending_verifiers.pop(phone, None)
        if verifier is None:
            return  # expired or replayed state — nothing to complete

        access_token = exchange_code_for_token(
            code, verifier, self._settings.oauth_redirect_uri
        )

        account = self._account_dao.get_by_phone(phone)
        if account is None:
            account = self._account_dao.create(
                Account(phone=phone, instamart_access_token=access_token)
            )
        else:
            account.instamart_access_token = access_token
            self._account_dao.update(account)

        group = Group(group_id=str(uuid.uuid4()), address_id=None)
        self._group_dao.create(group)
        self._group_account_dao.create(
            GroupAccount(group_id=group.group_id, account_id=phone, role=Role.HOLDER)
        )

        client = self._client_factory(access_token)
        addresses = client.get_addresses()
        if not addresses:
            self._messenger.send(
                phone,
                "No saved addresses found — please add one in the Instamart app, then message me again.",
            )
            return
        self._messenger.send(
            phone, f"Instamart linked!\n\n{self._address_prompt(addresses)}"
        )

    def _start_holder_onboarding(self, sender: str) -> None:
        verifier, challenge = generate_pkce_pair()
        self._pending_verifiers[sender] = verifier
        state = sign({"phone": sender}, self._settings.jwt_secret, OAUTH_STATE_EXPIRY)
        url = build_authorize_url(challenge, state, self._settings.oauth_redirect_uri)
        self._messenger.send(sender, f"Let's link your Instamart account:\n{url}")

    def _pending_address_selection_group(self, sender: str) -> Group | None:
        for membership in self._group_account_dao.get_by_account(sender):
            if membership.role != Role.HOLDER:
                continue
            group = self._group_dao.get_by_id(membership.group_id)
            if group is not None and group.address_id is None:
                return group
        return None

    def _complete_address_selection(self, sender: str, group: Group, body: str) -> None:
        account = self._account_dao.get_by_phone(sender)
        client = self._client_factory(account.instamart_access_token)
        addresses = client.get_addresses()
        if not addresses:
            self._messenger.send(
                sender,
                "No saved addresses found. Please add one in the Instamart app, "
                "then message me again.",
            )
            return

        try:
            choice = addresses[int(body.strip()) - 1]
        except (ValueError, IndexError):
            # Re-show the options rather than just scolding. The list is
            # otherwise only printed once, right after OAuth — so anyone who
            # arrives here another way (or replies with anything unexpected)
            # would be asked for a number they have never seen.
            self._messenger.send(sender, self._address_prompt(addresses))
            return

        group.address_id = choice.id
        self._group_dao.update(group)
        self._messenger.send(
            sender,
            f"Delivering to [{choice.tag}] {choice.line}. Household created — message 'invite' to add flatmates.",
        )

    def _address_prompt(self, addresses: list) -> str:
        listing = "\n".join(
            f"{i}. [{a.tag}] {a.line}" for i, a in enumerate(addresses, 1)
        )
        return f"Which address should this household deliver to?\n{listing}\n\nReply with the number."

    def _generate_invite(self, sender: str) -> None:
        holder_membership = next(
            (
                m
                for m in self._group_account_dao.get_by_account(sender)
                if m.role == Role.HOLDER
            ),
            None,
        )
        if holder_membership is None:
            self._messenger.send(sender, "Only the account holder can invite members.")
            return
        token_id = str(uuid.uuid4())
        token = sign(
            {"group_id": holder_membership.group_id, "token_id": token_id},
            self._settings.jwt_secret,
            INVITE_EXPIRY,
        )
        # wa.me wants the number without a leading '+'.
        bot_number = self._settings.twilio_whatsapp_from.lstrip("+")
        link = f"https://wa.me/{bot_number}?text={urllib.parse.quote(token)}"
        self._messenger.send(
            sender, f"Share this invite link (valid 24h, one-time use):\n{link}"
        )

    def _looks_like_invite_token(self, body: str) -> bool:
        return body.count(".") == 2

    def _consume_invite(self, sender: str, token: str) -> None:
        try:
            payload = verify(token, self._settings.jwt_secret)
        except jwt.PyJWTError:
            self._messenger.send(sender, "That invite link is invalid or expired.")
            return

        token_id, group_id = payload["token_id"], payload["group_id"]
        if self._invite_token_dao.is_consumed(token_id):
            self._messenger.send(
                sender, "That invite link has already been used. Ask for a fresh one."
            )
            return

        if self._account_dao.get_by_phone(sender) is None:
            self._account_dao.create(Account(phone=sender))
        if self._group_account_dao.get_by_group_and_account(group_id, sender) is None:
            self._group_account_dao.create(
                GroupAccount(group_id=group_id, account_id=sender, role=Role.MEMBER)
            )
        self._invite_token_dao.create(
            InviteToken(token_id=token_id, consumed_at=datetime.now(timezone.utc))
        )
        self._messenger.send(
            sender, "Welcome to HumaraCart! You've joined the household."
        )
