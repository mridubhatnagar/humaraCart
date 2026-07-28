"""Router tests: intent -> messages, broadcast, and the full demo script.

Run with:  python -m unittest discover -s tests
"""

import unittest

from app.cart_service import CartService
from app.config import seed_household
from app.instamart.mock import MockInstamartClient
from app.models import Action, Intent
from app.router import Router


class RouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hh = seed_household()
        self.priya = self.hh.account_holder
        self.rahul = self.hh.member_by_phone(self.hh.members[1].phone)
        self.router = Router(CartService(MockInstamartClient()))

    def handle(self, sender, action, item=None, qty=1):
        return self.router.handle(self.hh, sender, Intent(action, item, qty))

    def test_add_broadcasts_to_all_members(self) -> None:
        msgs = self.handle(self.priya, Action.ADD, "milk")
        self.assertEqual({m.to.name for m in msgs}, {"Priya", "Rahul"})
        self.assertTrue(all("Amul Taaza Milk" in m.text for m in msgs))

    def test_show_replies_only_to_sender(self) -> None:
        self.handle(self.priya, Action.ADD, "milk")
        msgs = self.handle(self.rahul, Action.SHOW)
        self.assertEqual([m.to.name for m in msgs], ["Rahul"])
        self.assertIn("Amul Taaza Milk", msgs[0].text)

    def test_duplicate_replies_only_to_sender(self) -> None:
        self.handle(self.priya, Action.ADD, "milk")
        msgs = self.handle(self.rahul, Action.ADD, "milk")
        self.assertEqual([m.to.name for m in msgs], ["Rahul"])
        self.assertIn("already on the list", msgs[0].text)
        self.assertIn("added by Priya", msgs[0].text)

    def test_ready_nudges_account_holder(self) -> None:
        self.handle(self.priya, Action.ADD, "milk")
        msgs = self.handle(self.rahul, Action.READY)
        holder_msgs = [m for m in msgs if m.to.name == "Priya"]
        self.assertTrue(holder_msgs)
        self.assertIn("ready", holder_msgs[0].text.lower())

    def test_send_link_restricted_to_account_holder(self) -> None:
        self.handle(self.priya, Action.ADD, "milk")
        msgs = self.handle(self.rahul, Action.SEND_LINK)
        self.assertIn("account holder", msgs[0].text)

    def test_send_link_summary_for_account_holder(self) -> None:
        self.handle(self.priya, Action.ADD, "milk", 2)
        self.handle(self.rahul, Action.ADD, "chips")
        msgs = self.handle(self.priya, Action.SEND_LINK)
        text = msgs[0].text
        self.assertIn("Amul Taaza Milk", text)
        self.assertIn("Lay's Classic", text)
        self.assertIn(str(66 * 2 + 20), text)  # total
        self.assertIn("ready on Instamart", text)

    def test_full_demo_script_runs_clean(self) -> None:
        """Walks the exact locked demo script and checks the key beats."""
        self.handle(self.priya, Action.ADD, "milk")       # Priya adds milk
        self.handle(self.rahul, Action.ADD, "detergent")  # Rahul adds detergent
        dup = self.handle(self.rahul, Action.ADD, "milk")  # money shot
        self.assertIn("already on the list", dup[0].text)
        self.handle(self.priya, Action.ADD, "chips")      # Priya adds chips
        rm = self.handle(self.rahul, Action.REMOVE, "detergent")
        self.assertEqual({m.to.name for m in rm}, {"Priya", "Rahul"})  # broadcast
        show = self.handle(self.rahul, Action.SHOW)
        self.assertIn("Amul Taaza Milk", show[0].text)
        self.assertIn("Lay's Classic", show[0].text)
        self.assertNotIn("Surf Excel", show[0].text)  # detergent removed
        link = self.handle(self.priya, Action.SEND_LINK)
        self.assertIn("ready on Instamart", link[0].text)


if __name__ == "__main__":
    unittest.main()
