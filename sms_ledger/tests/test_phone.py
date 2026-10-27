"""The phone app's screens: the month's money, the feed, and fixing a message.

bench --site <site> run-tests --app sms_ledger --module sms_ledger.tests.test_phone
"""

import frappe

from sms_ledger import phone
from sms_ledger.tests.test_posting import KCB, KCB_CREDIT, MPESA, RECEIVED, TILL, TO_KCB, PostingCase


class TestPhone(PostingCase):
	def test_the_month_counts_income_and_spending_but_not_moving_money_between_your_own_accounts(self):
		self.send((MPESA, RECEIVED), (MPESA, TILL), (MPESA, TO_KCB), (KCB, KCB_CREDIT))
		board = phone.dashboard("2025-10")
		self.assertEqual(board["totals"], {"in": 1500.0, "out": 350.0, "charges": 30.0, "net": 1120.0})
		self.assertEqual(board["top_payees"], [{"label": "Naivas Supermarket", "amount": 350.0}])
		balances = {b["source"]: b["balance"] for b in board["balances"]}
		self.assertEqual((balances["M-Pesa"], balances["KCB"]), (2620.0, 12000.0))

	def test_the_daily_chart_ends_on_the_last_day_of_a_past_month(self):
		self.send((MPESA, RECEIVED))
		daily = phone.dashboard("2025-10")["daily"]
		self.assertEqual((len(daily), daily[-1]["date"]), (14, "2025-10-31"))
		self.assertEqual(next(d for d in daily if d["date"] == "2025-10-20")["in"], 1500.0)

	def test_the_attention_filter_lists_only_messages_that_failed_or_could_not_be_read(self):
		frappe.db.set_single_value("SMS Ledger Settings", "default_expense_account", None)
		self._clear_caches()
		self.send((MPESA, TILL), (MPESA, RECEIVED))
		feed = phone.activity(status="attention")
		self.assertEqual([(r.reference, r.status) for r in feed], [("TJK3CDE4FG", "Failed")])

	def test_retry_posts_a_failed_message_once_its_cause_is_fixed(self):
		frappe.db.set_single_value("SMS Ledger Settings", "default_expense_account", None)
		self._clear_caches()
		self.send((MPESA, TILL))
		frappe.db.set_single_value("SMS Ledger Settings", "default_expense_account", self.expense)
		self._clear_caches()
		name = self.txn("TJK3CDE4FG").name
		self.assertEqual(phone.retry(name)["status"], "Posted")

	def test_recategorising_reposts_to_the_new_account_and_can_remember_the_payee(self):
		self.send((MPESA, TILL))
		name = self.txn("TJK3CDE4FG").name
		result = phone.recategorise(name, self.supplies, remember=1)
		self.assertEqual((result["status"], result["offset_account"]), ("Posted", self.supplies))
		self.assertEqual(
			frappe.db.get_value("SMS Ledger Rule", {"match_value": "Naivas Supermarket"}, "account"),
			self.supplies,
		)

	def test_a_message_cannot_be_filed_under_a_bank_account(self):
		self.send((MPESA, TILL))
		with self.assertRaisesRegex(frappe.ValidationError, "Pick an income or expense account"):
			phone.recategorise(self.txn("TJK3CDE4FG").name, self.kcb)
