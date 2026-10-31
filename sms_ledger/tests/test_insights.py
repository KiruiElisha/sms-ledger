"""Insights rank where money went, compare with last month, and leave transfers out."""

import unittest

import frappe

from sms_ledger import phone


def _row(direction, amount, account=None, counterparty=None, date="2026-10-05", transfer=0):
	return frappe._dict(
		direction=direction,
		amount=amount,
		offset_account=account,
		counterparty=counterparty,
		transaction_date=date,
		is_transfer=transfer,
		charges=0,
	)


class TestInsights(unittest.TestCase):
	def test_categories_keep_the_biggest_and_fold_the_rest_into_other(self):
		rows = [_row("Out", amount, f"Acc {i} - CO") for i, amount in enumerate([500, 400, 300, 200])]
		ranked = phone._ranked(rows, "Out", "offset_account", 2)
		self.assertEqual(
			[(r["label"], r["amount"]) for r in ranked], [("Acc 0", 500), ("Acc 1", 400), ("Other", 500)]
		)

	def test_transfers_between_own_accounts_are_not_spending(self):
		rows = [_row("Out", 100, "Food"), _row("Out", 900, "Bank", transfer=1)]
		self.assertEqual(phone._ranked(rows, "Out", "offset_account", 5), [{"label": "Food", "amount": 100}])

	def test_spending_is_summed_by_weekday(self):
		rows = [_row("Out", 100, date="2026-10-05"), _row("Out", 50, date="2026-10-12")]  # both Mondays
		self.assertEqual(phone._weekdays(rows)[0], {"label": "Mon", "amount": 150})

	def test_change_is_a_percentage_of_last_month_and_none_without_one(self):
		self.assertEqual((phone._change(150, 100), phone._change(50, 0)), (50.0, None))

	def test_savings_rate_is_net_as_a_share_of_money_in(self):
		totals = {"in": 1000.0, "out": 600.0, "charges": 30.0, "net": 370.0}
		stats = phone._stats(
			[_row("In", 1000), _row("Out", 600)], totals, "2026-10-01", "2026-10-31", today="2026-10-10"
		)
		self.assertEqual(stats["average_daily_out"], 60.0)
		self.assertEqual(
			(stats["savings_rate"], stats["charges_share"], stats["transactions"]), (37.0, 5.0, 2)
		)
