# Copyright (c) 2026, Sol and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

ACCOUNT_FIELDS = (
	"default_income_account",
	"default_expense_account",
	"charges_account",
	"cash_account",
	"airtime_account",
	"savings_transfer_account",
)


class SMSLedgerSettings(Document):
	def validate(self):
		for fieldname in ACCOUNT_FIELDS:
			account = self.get(fieldname)
			if not account:
				continue
			company, is_group = frappe.db.get_value("Account", account, ["company", "is_group"])
			label = self.meta.get_label(fieldname)
			if company != self.company:
				frappe.throw(
					_("{0}: account {1} does not belong to {2}").format(label, account, self.company)
				)
			if is_group:
				frappe.throw(_("{0}: {1} is a group account. Pick a ledger account.").format(label, account))
		if (
			self.cost_center
			and frappe.db.get_value("Cost Center", self.cost_center, "company") != self.company
		):
			frappe.throw(_("Cost Center {0} does not belong to {1}").format(self.cost_center, self.company))
		if (self.transfer_match_days or 0) < 0:
			self.transfer_match_days = 0
