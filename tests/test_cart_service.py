"""Core-engine tests. These must stay green — they are the demo's foundation.

Run with:  python -m unittest discover -s tests
"""

import unittest

from app.cart_service import AddStatus, CartService, RemoveStatus
from app.instamart.mock import MockInstamartClient

HH = "household_1"


class CartServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = CartService(MockInstamartClient())

    # -- add ---------------------------------------------------------------

    def test_add_resolves_and_adds(self) -> None:
        res = self.svc.add(HH, "milk", 1, "Priya")
        self.assertEqual(res.status, AddStatus.ADDED)
        self.assertEqual(res.product.name, "Amul Taaza Milk 1L")
        self.assertEqual([l.product.id for l in self.svc.items(HH)], ["p_milk"])

    def test_add_synonym_resolves(self) -> None:
        res = self.svc.add(HH, "doodh", 1, "Priya")
        self.assertEqual(res.status, AddStatus.ADDED)
        self.assertEqual(res.product.id, "p_milk")

    def test_add_is_case_and_space_insensitive(self) -> None:
        self.assertEqual(self.svc.add(HH, "  MILK ", 1, "Priya").status, AddStatus.ADDED)

    def test_unknown_item_not_found(self) -> None:
        self.assertEqual(self.svc.add(HH, "unicorn", 1, "Priya").status, AddStatus.NOT_FOUND)

    def test_out_of_stock_is_unavailable(self) -> None:
        res = self.svc.add(HH, "butter", 1, "Priya")
        self.assertEqual(res.status, AddStatus.UNAVAILABLE)
        self.assertEqual(self.svc.items(HH), [])  # not added to cart

    # -- the money shot: duplicate detection -------------------------------

    def test_duplicate_is_caught_and_attributed(self) -> None:
        self.svc.add(HH, "milk", 1, "Priya")
        res = self.svc.add(HH, "milk", 1, "Rahul")
        self.assertEqual(res.status, AddStatus.DUPLICATE)
        self.assertEqual(res.existing_added_by, "Priya")
        # Still exactly one milk in the cart.
        self.assertEqual([l.product.id for l in self.svc.items(HH)], ["p_milk"])

    # -- remove ------------------------------------------------------------

    def test_remove_existing(self) -> None:
        self.svc.add(HH, "milk", 1, "Priya")
        res = self.svc.remove(HH, "milk", "Rahul")
        self.assertEqual(res.status, RemoveStatus.REMOVED)
        self.assertEqual(self.svc.items(HH), [])

    def test_remove_absent_item(self) -> None:
        self.assertEqual(self.svc.remove(HH, "milk", "Rahul").status, RemoveStatus.NOT_IN_CART)

    def test_remove_unknown_item(self) -> None:
        self.assertEqual(self.svc.remove(HH, "unicorn", "Rahul").status, RemoveStatus.NOT_FOUND)

    # -- attribution & isolation -------------------------------------------

    def test_added_by_tracked_per_item(self) -> None:
        self.svc.add(HH, "milk", 1, "Priya")
        self.svc.add(HH, "chips", 1, "Rahul")
        by = {l.product.id: l.added_by for l in self.svc.items(HH)}
        self.assertEqual(by, {"p_milk": "Priya", "p_chips": "Rahul"})

    def test_households_are_isolated(self) -> None:
        self.svc.add("hh_a", "milk", 1, "Priya")
        self.assertEqual(self.svc.items("hh_b"), [])

    def test_total_reflects_quantity_and_price(self) -> None:
        self.svc.add(HH, "milk", 2, "Priya")  # 66 * 2
        self.svc.add(HH, "chips", 1, "Rahul")  # 20
        self.assertEqual(self.svc.total(HH), 66 * 2 + 20)


if __name__ == "__main__":
    unittest.main()
