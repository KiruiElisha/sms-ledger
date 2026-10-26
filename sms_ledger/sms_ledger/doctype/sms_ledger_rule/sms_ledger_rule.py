# Copyright (c) 2026, Sol and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class SMSLedgerRule(Document):
	def validate(self):
		if self.match_type == "Regex":
			try:
				re.compile(self.match_value or "")
			except re.error as e:
				frappe.throw(_("Invalid regex: {0}").format(e))
		if self.action == "Post" and not (self.account or self.party):
			frappe.throw(_("Set an Account, a Party, or both."))
		if self.party and not self.party_type:
			frappe.throw(_("Set the Party Type."))
		if self.account and frappe.db.get_value("Account", self.account, "is_group"):
			frappe.throw(_("{0} is a group account. Pick a ledger account.").format(self.account))

	def on_update(self):
		frappe.cache.delete_value("sms_ledger:rules")

	def on_trash(self):
		frappe.cache.delete_value("sms_ledger:rules")
