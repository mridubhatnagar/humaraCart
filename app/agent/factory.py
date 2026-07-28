"""Assembles the real agent: OpenAI model, tool schemas, graph, checkpointer.

Kept apart from `build_graph` so the graph itself stays free of any OpenAI or
SQLite specifics — tests build the same graph with a scripted model and an
in-memory checkpointer.
"""

from __future__ import annotations

import sqlite3

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver

from app.accounts.dao import IAccountDAO
from app.agent.graph import build_graph
from app.agent.prompt import prompt_for
from app.agent.service import AgentService
from app.agent.tools import build_tools, schemas_for
from app.cart.service import CartService
from app.instamart.client import IInstamartClient
from app.instamart.mcp_client import McpInstamartClient
from app.settings import Settings


def make_checkpointer(database_url: str) -> SqliteSaver:
    """A durable checkpointer, so a restart mid-recording doesn't lose a
    conversation that's paused waiting on someone to pick a variant."""
    path = database_url.replace("sqlite:///", "", 1)
    connection = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(connection)


def build_agent(
    settings: Settings,
    client: IInstamartClient,
    cart_service: CartService,
    account_dao: IAccountDAO,
    group_account_dao,
    checkpointer,
    is_holder: bool = True,
):
    # Tools and prompt both vary by role: a member is not given the schemas for
    # paying, so it is not a capability the model has rather than one it is
    # merely asked not to use.
    model = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).bind_tools(schemas_for(is_holder))
    tools = build_tools(client, cart_service, account_dao, group_account_dao)
    return build_graph(
        model, tools, checkpointer, system_prompt=prompt_for(is_holder)
    )


class AgentAssembler:
    """Builds a ready `AgentService` for one household.

    The Instamart client carries the *holder's* OAuth token, so it cannot be an
    application-wide singleton — every household talks to Swiggy as a different
    account. Assembly is per-message, which is cheap (pure wiring, no network);
    the checkpointer is shared, so conversation state still persists.
    """

    def __init__(
        self,
        settings: Settings,
        account_dao: IAccountDAO,
        group_account_dao,
        item_cart_dao,
        messenger,
        checkpointer,
        client_factory=None,
    ) -> None:
        self._settings = settings
        self._account_dao = account_dao
        self._group_account_dao = group_account_dao
        self._item_cart_dao = item_cart_dao
        self._messenger = messenger
        self._checkpointer = checkpointer
        self._client_factory = client_factory or McpInstamartClient

    def for_group(self, group_id: str, sender: str | None = None):
        """Returns an `AgentService`, or None if the holder has no live token.

        `sender` decides which tools get bound — omit it and you get the
        holder's full set.
        """
        holder = self._group_account_dao.get_holder(group_id)
        if holder is None:
            return None
        is_holder = sender is None or sender == holder.account_id
        account = self._account_dao.get_by_phone(holder.account_id)
        if account is None or not account.instamart_access_token:
            return None

        client = self._client_factory(account.instamart_access_token)
        cart_service = CartService(client, self._item_cart_dao)
        graph = build_agent(
            self._settings,
            client,
            cart_service,
            self._account_dao,
            self._group_account_dao,
            self._checkpointer,
            is_holder=is_holder,
        )
        return AgentService(
            graph,
            cart_service,
            self._account_dao,
            self._group_account_dao,
            self._messenger,
        )
