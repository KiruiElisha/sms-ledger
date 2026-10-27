"""End to end on a real ERPNext site: SMS in through the phone API, accounting entries out.

    bench --site <site> run-tests --app sms_ledger --module sms_ledger.tests.test_posting

Needs a company with a "Bank Accounts" and an "Indirect Expenses" group (the standard chart).
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from sms_ledger import api, posting

MPESA = "MPESA"
KCB = "KCB"

RECEIVED = (
	"TJK1ABC2DE Confirmed.You have received Ksh1,500.00 from JOHN DOE 0712345678 on 20/10/25 at 3:15 PM "
	"New M-PESA balance is Ksh5,000.00. Earn interest daily on Ziidi MMF,Dial *334#"
)
TO_KCB = (
	"TJK2BCD3EF Confirmed. Ksh2,000.00 sent to KCB Paybill AC for account 1234567890 on 20/10/25 at 4:00 PM "
	"New M-PESA balance is Ksh2,970.00. Transaction cost, Ksh30.00."
)
KCB_CREDIT = (
	"Dear Customer, KES 2,000.00 has been credited to your A/C ****7890 on 20/10/2025 at 16:01 from MPESA "
	"Ref TJK2BCD3EF. Avail Bal KES 12,000.00"
)
KCB_OTHER_ACCOUNT = (
	"Dear Customer, KES 9,000.00 has been credited to your A/C ****1111 on 20/10/2025 at 16:05 from JANE "
	"Ref FT2529300001. Avail Bal KES 9,000.00"
)
TILL = (
	"TJK3CDE4FG Confirmed. Ksh350.00 paid to NAIVAS SUPERMARKET on 21/10/25 at 9:10 AM.New M-PESA balance is "
	"Ksh2,620.00. Transaction cost, Ksh0.00."
)
REVERSAL = (
	"TJK4DEF5GH Confirmed. Reversal of transaction TJK3CDE4FG has been successfully reversed. Ksh350.00 is "
	"credited to your M-PESA account on 21/10/25 at 10:00 AM. New M-PESA account balance is Ksh2,970.00."
)
TO_EQUITY = (
	"TJK5EFG6HI Confirmed. Ksh4,000.00 sent to EQUITY BANK for account 0170299999999 on 22/10/25 at 11:00 AM "
	"New M-PESA balance is Ksh1,000.00. Transaction cost, Ksh0.00."
)
KCB_TO_MPESA = (
	"MBNHE3TF7P9589O2  KES 2,000.00 sent from 128****079 to 254****381 - ELISHA KIPKEMOI KIRUI on "
	"2026-10-26 09:46:06 AM. M-PESA REF: UJQIGBPD21"
)
KCB_RECIPIENT_NOTICE = (
	"MBNHE3TF7P9589O2 Confirmed.  KES 2,000.00 received from ELISHA KIPKEMOI KIRUI - 128****079 on "
	"2026-10-26 09:46:06 AM via KCB."
)
MPESA_FROM_KCB = (
	"UJQIGBPD21 Confirmed.You have received Ksh2,000.00 from KCB 1 501901 on 26/10/26 at 9:46 AM New M-PESA "
	"balance is Ksh2,028.97. See all your balances now https://saf.cx/kWQpy."
)
PROMO = "Pata bonus! Buy bundles now and get 50% extra. Dial *544#"


def _account(company, abbr, name, parent, account_type=None, root_type=None):
	full = f"{name} - {abbr}"
	if not frappe.db.exists("Account", full):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": name,
				"company": company,
				"parent_account": f"{parent} - {abbr}",
				"account_type": account_type,
				"root_type": root_type,
			}
		).insert(ignore_permissions=True)
	return full


def _gl(voucher):
	return {
		r.account: flt(r.debit) - flt(r.credit)
		for r in frappe.get_all(
			"GL Entry", {"voucher_no": voucher, "is_cancelled": 0}, ["account", "debit", "credit"]
		)
	}


class TestPosting(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		company = frappe.get_all("Company", pluck="name", limit=1)[0]
		abbr = frappe.get_cached_value("Company", company, "abbr")
		self.mpesa = _account(company, abbr, "M-Pesa", "Bank Accounts", "Bank")
		self.kcb = _account(company, abbr, "KCB", "Bank Accounts", "Bank")
		self.charges = _account(company, abbr, "Bank Charges", "Indirect Expenses", "Chargeable")
		self.supplies = _account(company, abbr, "Office Supplies", "Indirect Expenses")
		self.income = frappe.get_all(
			"Account",
			{"company": company, "root_type": "Income", "is_group": 0},
			pluck="name",
			order_by="name",
		)[0]
		self.expense = _account(company, abbr, "General Expenses", "Indirect Expenses")
		settings = frappe.get_doc("SMS Ledger Settings")
		settings.update(
			{
				"enabled": 1,
				"company": company,
				"auto_post": 1,
				"submit_entries": 1,
				"default_posting_mode": "Journal Entry",
				"auto_create_party": 1,
				"auto_create_bank": 1,
				"title_case_names": 1,
				"default_income_account": self.income,
				"default_expense_account": self.expense,
				"charges_account": self.charges,
				"transfer_match_days": 2,
				"auto_fix_transfer_duplicates": 1,
			}
		)
		settings.save(ignore_permissions=True)
		for name, account, mask in (("M-Pesa", self.mpesa, None), ("KCB", self.kcb, "1234567890")):
			source = frappe.get_doc("SMS Source", name)
			source.update({"enabled": 1, "account": account, "account_mask": mask})
			source.save(ignore_permissions=True)
		self._clear_caches()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self._clear_caches()

	def _clear_caches(self):
		frappe.clear_document_cache("SMS Ledger Settings", "SMS Ledger Settings")
		for key in ("sms_ledger:sources", "sms_ledger:rules"):
			frappe.cache.delete_value(key)
		for name in ("M-Pesa", "KCB"):
			frappe.clear_document_cache("SMS Source", name)

	def send(self, *messages):
		"""The phone app's upload, then the background job it queues."""
		out = api.ingest(
			[
				{"id": i, "sender": s, "body": b, "timestamp": 1761000000000 + i}
				for i, (s, b) in enumerate(messages)
			],
			device_id="test-phone",
		)
		# The job commits after each message; here everything is rolled back after the test instead.
		with mock.patch.object(frappe.db, "commit"):
			posting.process_transactions([r["name"] for r in out["results"] if r["status"] == "accepted"])
		return out

	def txn(self, reference):
		return frappe.get_doc("SMS Transaction", {"reference": reference})

	def test_money_received_is_income_and_the_sender_becomes_a_customer_with_their_phone(self):
		self.send((MPESA, RECEIVED))
		txn = self.txn("TJK1ABC2DE")
		self.assertEqual(txn.status, "Posted", txn.error)
		self.assertEqual(_gl(txn.journal_entry), {self.mpesa: 1500.0, self.income: -1500.0})
		self.assertEqual((txn.party_type, txn.party), ("Customer", "John Doe"))
		self.assertEqual(posting.find_party_by_phone("Customer", "0712345678"), "John Doe")

	def test_paying_your_own_kcb_account_is_one_transfer_and_only_the_cost_is_an_expense(self):
		self.send((MPESA, TO_KCB), (KCB, KCB_CREDIT))
		# Both messages carry the M-PESA code: the KCB alert quotes it as its reference.
		mpesa = frappe.get_doc("SMS Transaction", {"source": "M-Pesa"})
		kcb = frappe.get_doc("SMS Transaction", {"source": "KCB"})
		self.assertEqual({mpesa.status, kcb.status}, {"Posted", "Linked"}, (mpesa.error, kcb.error))
		posted = mpesa if mpesa.status == "Posted" else kcb
		entries = {}
		for doc in (mpesa, kcb):
			for field in ("journal_entry", "charges_entry"):
				if doc.get(field):
					for account, amount in _gl(doc.get(field)).items():
						entries[account] = entries.get(account, 0) + amount
		self.assertEqual(entries, {self.kcb: 2000.0, self.mpesa: -2030.0, self.charges: 30.0})
		self.assertEqual(
			frappe.db.get_value("Journal Entry", posted.journal_entry, "voucher_type"), "Contra Entry"
		)

	def test_the_same_sms_sent_twice_is_recorded_once(self):
		self.send((MPESA, TILL))
		again = self.send((MPESA, "  " + TILL.replace(". ", ".  ") + " "))
		self.assertEqual(again["results"][0]["status"], "duplicate")
		self.assertEqual(frappe.db.count("SMS Transaction", {"reference": "TJK3CDE4FG"}), 1)

	def test_a_till_payment_is_an_expense_and_its_reversal_undoes_it(self):
		self.send((MPESA, TILL), (MPESA, REVERSAL))
		paid, reversed_ = self.txn("TJK3CDE4FG"), self.txn("TJK4DEF5GH")
		self.assertEqual((paid.status, reversed_.status), ("Posted", "Posted"), (paid.error, reversed_.error))
		self.assertEqual(_gl(paid.journal_entry), {self.expense: 350.0, self.mpesa: -350.0})
		self.assertEqual(_gl(reversed_.journal_entry), {self.mpesa: 350.0, self.expense: -350.0})
		self.assertEqual((paid.party_type, paid.party), ("Supplier", "Naivas Supermarket"))

	def test_a_rule_sends_a_counterparty_to_its_own_account(self):
		frappe.get_doc(
			{
				"doctype": "SMS Ledger Rule",
				"rule_name": "Naivas",
				"enabled": 1,
				"priority": 10,
				"match_field": "Counterparty",
				"match_type": "Contains",
				"match_value": "naivas",
				"action": "Post",
				"account": self.supplies,
			}
		).insert(ignore_permissions=True)
		self.send((MPESA, TILL))
		self.assertEqual(
			_gl(self.txn("TJK3CDE4FG").journal_entry), {self.supplies: 350.0, self.mpesa: -350.0}
		)

	def test_a_kcb_alert_for_someone_elses_account_is_ignored(self):
		self.send((KCB, KCB_OTHER_ACCOUNT))
		txn = frappe.get_doc("SMS Transaction", {"source": "KCB"})
		self.assertEqual(txn.status, "Ignored")
		self.assertIn("****1111", txn.error)
		self.assertFalse(txn.journal_entry)

	def test_paying_another_bank_creates_that_bank_and_the_suppliers_bank_account(self):
		frappe.db.delete("Bank", {"name": "Equity Bank"})
		self.send((MPESA, TO_EQUITY))
		txn = self.txn("TJK5EFG6HI")
		self.assertEqual(txn.status, "Posted", txn.error)
		self.assertTrue(frappe.db.exists("Bank", "Equity Bank"))
		self.assertEqual(txn.counterparty_bank, "Equity Bank")

	def test_promotions_and_unknown_senders_are_not_recorded(self):
		out = self.send((MPESA, PROMO), ("MPESA-PROMO", RECEIVED), ("Safaricom", RECEIVED))
		self.assertEqual([r["status"] for r in out["results"]], ["skipped", "skipped", "skipped"])
		self.assertFalse(frappe.db.exists("SMS Transaction", {"reference": "TJK1ABC2DE"}))

	def test_only_the_device_role_or_accounts_managers_may_upload(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.ingest([{"sender": MPESA, "body": RECEIVED}])

	def test_a_transfer_is_still_recorded_once_when_the_bank_alert_arrives_first(self):
		self.send((KCB, KCB_CREDIT))
		self.send((MPESA, TO_KCB))
		mpesa = frappe.get_doc("SMS Transaction", {"source": "M-Pesa"})
		kcb = frappe.get_doc("SMS Transaction", {"source": "KCB"})
		self.assertEqual({mpesa.status, kcb.status}, {"Posted", "Linked"}, (mpesa.error, kcb.error))
		live = [
			doc.get(f)
			for doc in (mpesa, kcb)
			for f in ("journal_entry", "charges_entry")
			if doc.get(f) and frappe.db.get_value("Journal Entry", doc.get(f), "docstatus") == 1
		]
		totals = {}
		for je in live:
			for account, amount in _gl(je).items():
				totals[account] = totals.get(account, 0) + amount
		self.assertEqual(totals, {self.kcb: 2000.0, self.mpesa: -2030.0, self.charges: 30.0})

	def test_payment_entry_mode_records_money_received_against_the_customer(self):
		frappe.db.set_single_value("SMS Ledger Settings", "default_posting_mode", "Payment Entry")
		self._clear_caches()
		self.send((MPESA, RECEIVED))
		txn = self.txn("TJK1ABC2DE")
		self.assertEqual(txn.status, "Posted", txn.error)
		pe = frappe.get_doc("Payment Entry", txn.payment_entry)
		self.assertEqual(
			(pe.payment_type, pe.party, pe.paid_to, pe.paid_amount, pe.docstatus),
			("Receive", "John Doe", self.mpesa, 1500.0, 1),
		)

	def test_kcb_to_mpesa_is_one_transfer_and_kcbs_notice_to_the_recipient_posts_nothing(self):
		frappe.db.set_value("SMS Source", "KCB", "account_mask", "1280000079")
		self._clear_caches()
		self.send((KCB, KCB_TO_MPESA), (KCB, KCB_RECIPIENT_NOTICE), (MPESA, MPESA_FROM_KCB))
		notice = frappe.get_all("SMS Transaction", {"source": "KCB", "status": "Ignored"}, ["error"])
		self.assertEqual(len(notice), 1)
		self.assertIn("Notice to the recipient", notice[0].error)
		mpesa = self.txn("UJQIGBPD21")
		kcb = frappe.get_doc("SMS Transaction", {"source": "KCB", "status": ["!=", "Ignored"]})
		self.assertEqual({mpesa.status, kcb.status}, {"Posted", "Linked"}, (mpesa.error, kcb.error))
		posted = mpesa if mpesa.status == "Posted" else kcb
		self.assertEqual(_gl(posted.journal_entry), {self.mpesa: 2000.0, self.kcb: -2000.0})

	def test_an_account_in_another_currency_is_converted_instead_of_failing(self):
		company = frappe.db.get_single_value("SMS Ledger Settings", "company")
		currency = frappe.get_cached_value("Company", company, "default_currency")
		foreign = "USD" if currency != "USD" else "EUR"
		abbr = frappe.get_cached_value("Company", company, "abbr")
		account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"Travel {foreign}",
				"company": company,
				"parent_account": f"Indirect Expenses - {abbr}",
				"account_currency": foreign,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Currency Exchange",
				"date": "2025-10-01",
				"from_currency": foreign,
				"to_currency": currency,
				"exchange_rate": 125,
				"for_buying": 1,
				"for_selling": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_single_value("SMS Ledger Settings", "default_expense_account", account.name)
		self._clear_caches()
		self.send((MPESA, TILL))
		paid = self.txn("TJK3CDE4FG")
		self.assertEqual(paid.status, "Posted", paid.error)
		je = frappe.get_doc("Journal Entry", paid.journal_entry)
		self.assertTrue(je.multi_currency)
		row = next(r for r in je.accounts if r.account == account.name)
		self.assertEqual((flt(row.debit_in_account_currency, 2), flt(row.debit, 2)), (2.8, 350.0))

	def test_a_failed_posting_keeps_the_amount_and_says_why_first(self):
		frappe.db.set_single_value("SMS Ledger Settings", "default_expense_account", None)
		self._clear_caches()
		self.send((MPESA, TILL))
		paid = self.txn("TJK3CDE4FG")
		self.assertEqual((paid.status, paid.amount, paid.direction), ("Failed", 350.0, "Out"))
		self.assertTrue(paid.error.startswith("No offset account could be determined"), paid.error)
