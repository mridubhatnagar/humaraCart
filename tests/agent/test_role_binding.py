"""Role decides what the model can even attempt.

Gating a tool's body is not enough on its own: the model will recite payment
options it saw earlier in the shared household thread without calling anything.
Withholding the schema removes the capability instead of asking it not to.
"""

from __future__ import annotations

from app.agent.prompt import prompt_for
from app.agent.tools import schemas_for


def names(schemas):
    return {s["function"]["name"] for s in schemas}


def test_member_has_no_way_to_pay():
    assert "checkout" not in names(schemas_for(is_holder=False))
    assert "get_payment_options" not in names(schemas_for(is_holder=False))


def test_member_gets_a_correct_alternative():
    """Otherwise "checkout" has no valid action and the model improvises."""
    assert "nudge_holder" in names(schemas_for(is_holder=False))


def test_holder_can_pay_and_has_no_nudge_tool():
    holder_tools = names(schemas_for(is_holder=True))
    assert {"checkout", "get_payment_options"} <= holder_tools
    assert "nudge_holder" not in holder_tools


def test_cart_tools_are_shared_by_both_roles():
    shared = {"search_products", "update_cart", "get_cart"}
    assert shared <= names(schemas_for(is_holder=True))
    assert shared <= names(schemas_for(is_holder=False))


def test_prompt_tells_the_model_which_role_it_is_serving():
    assert "NOT the account holder" in prompt_for(is_holder=False)
    assert "IS the account holder" in prompt_for(is_holder=True)


def test_member_prompt_forbids_reciting_stale_payment_options():
    assert "saw some earlier" in prompt_for(is_holder=False)
