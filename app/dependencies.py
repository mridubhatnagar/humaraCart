"""Cross-cutting DI: DB session, DAOs, the Fernet cipher, Twilio signature
verification, the Messenger, and the onboarding service — injected via `Depends`.

`get_verified_twilio_form` is the one async function in this sync-first
codebase: Starlette's `Request.form()` has no sync API, so reading the
webhook body forces it — a small, isolated exception, not a redesign.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import lru_cache

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker
from twilio.request_validator import RequestValidator

from app.accounts.dao import AccountDAO, IAccountDAO
from app.agent.factory import AgentAssembler, make_checkpointer
from app.cart.dao import IItemCartDAO, ItemCartDAO
from app.conversation.service import ConversationService
from app.core.db import make_session_factory
from app.core.locks import IGroupLock, PostgresGroupLock
from app.groups.dao import GroupAccountDAO, GroupDAO, IGroupAccountDAO, IGroupDAO
from app.instamart.mcp_client import McpInstamartClient
from app.invites.dao import IInviteTokenDAO, InviteTokenDAO
from app.onboarding.service import OnboardingService
from app.settings import Settings, get_settings
from app.whatsapp.messenger import IMessenger
from app.whatsapp.twilio_messenger import TwilioMessenger

logger = logging.getLogger(__name__)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_settings().database_url)


def get_db() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_fernet(settings: Settings = Depends(get_settings)) -> Fernet:
    return Fernet(settings.token_encryption_key.encode())


def get_account_dao(
    session: Session = Depends(get_db), fernet: Fernet = Depends(get_fernet)
) -> IAccountDAO:
    return AccountDAO(session, fernet)


def get_group_dao(session: Session = Depends(get_db)) -> IGroupDAO:
    return GroupDAO(session)


def get_group_account_dao(session: Session = Depends(get_db)) -> IGroupAccountDAO:
    return GroupAccountDAO(session)


def get_item_cart_dao(session: Session = Depends(get_db)) -> IItemCartDAO:
    return ItemCartDAO(session)


def get_invite_token_dao(session: Session = Depends(get_db)) -> IInviteTokenDAO:
    return InviteTokenDAO(session)


async def get_verified_twilio_form(
    request: Request, settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(str(request.url), params, signature):
        logger.warning(
            "Rejected webhook request with invalid Twilio signature from %r",
            params.get("From"),
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    return params


def get_group_lock() -> IGroupLock:
    return PostgresGroupLock(_session_factory())


def get_messenger(settings: Settings = Depends(get_settings)) -> IMessenger:
    return TwilioMessenger(
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_whatsapp_from,
    )


@lru_cache
def _pending_oauth_verifiers() -> dict[str, str]:
    """Process-wide, short-lived: bridges the seconds between sending the
    authorize link and the browser's callback. Never persisted — acceptable
    for V1's single-process deployment; a multi-process setup would have to
    move this into the DB instead."""
    return {}


@lru_cache
def _checkpointer():
    """One shared checkpointer for the process — conversations paused at an
    interrupt survive restarts because it's backed by the same SQLite file."""
    return make_checkpointer(get_settings().database_url)


def get_agent_assembler(
    settings: Settings = Depends(get_settings),
    account_dao: IAccountDAO = Depends(get_account_dao),
    group_account_dao: IGroupAccountDAO = Depends(get_group_account_dao),
    item_cart_dao: IItemCartDAO = Depends(get_item_cart_dao),
    messenger: IMessenger = Depends(get_messenger),
) -> AgentAssembler:
    return AgentAssembler(
        settings=settings,
        account_dao=account_dao,
        group_account_dao=group_account_dao,
        item_cart_dao=item_cart_dao,
        messenger=messenger,
        checkpointer=_checkpointer(),
    )


def get_onboarding_service(
    account_dao: IAccountDAO = Depends(get_account_dao),
    group_dao: IGroupDAO = Depends(get_group_dao),
    group_account_dao: IGroupAccountDAO = Depends(get_group_account_dao),
    invite_token_dao: IInviteTokenDAO = Depends(get_invite_token_dao),
    messenger: IMessenger = Depends(get_messenger),
    settings: Settings = Depends(get_settings),
) -> OnboardingService:
    return OnboardingService(
        account_dao=account_dao,
        group_dao=group_dao,
        group_account_dao=group_account_dao,
        invite_token_dao=invite_token_dao,
        messenger=messenger,
        settings=settings,
        pending_verifiers=_pending_oauth_verifiers(),
        client_factory=McpInstamartClient,
    )


def get_conversation_service(
    onboarding: OnboardingService = Depends(get_onboarding_service),
    account_dao: IAccountDAO = Depends(get_account_dao),
    assembler: AgentAssembler = Depends(get_agent_assembler),
    group_dao: IGroupDAO = Depends(get_group_dao),
    group_account_dao: IGroupAccountDAO = Depends(get_group_account_dao),
    messenger: IMessenger = Depends(get_messenger),
    group_lock: IGroupLock = Depends(get_group_lock),
) -> ConversationService:
    return ConversationService(
        onboarding=onboarding,
        agent_assembler=assembler,
        group_dao=group_dao,
        group_account_dao=group_account_dao,
        messenger=messenger,
        account_dao=account_dao,
        group_lock=group_lock,
    )
