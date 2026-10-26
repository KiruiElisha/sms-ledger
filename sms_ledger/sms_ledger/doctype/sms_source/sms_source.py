# Copyright (c) 2026, Sol and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from sms_ledger.parsers import PARSER_CUSTOM


class SMSSource(Document):
	def validate(self):
		self.validate_account()
		self.validate_senders()
		self.validate_patterns()
		self.set_bank()

	def on_update(self):
		frappe.cache.delete_value("sms_ledger:sources")

	def on_trash(self):
		frappe.cache.delete_value("sms_ledger:sources")

	def validate_account(self):
		if self.enabled and not self.account:
			frappe.throw(_("Set the Ledger Account before enabling this source."))
		if not self.account:
			return
		company = frappe.db.get_single_value("SMS Ledger Settings", "company")
		acc = frappe.db.get_value(
			"Account", self.account, ["company", "is_group", "account_type"], as_dict=True
		)
		if company and acc.company != company:
			frappe.throw(
				_("Account {0} does not belong to {1} (set in SMS Ledger Settings)").format(
					self.account, company
				)
			)
		if acc.is_group:
			frappe.throw(_("{0} is a group account. Pick a ledger account.").format(self.account))
		if acc.account_type not in ("Bank", "Cash"):
			frappe.msgprint(
				_(
					"{0} is not a Bank or Cash account. It will still work, but bank reconciliation and "
					"transfer detection expect a Bank / Cash account."
				).format(self.account),
				indicator="orange",
				alert=True,
			)

	def validate_senders(self):
		seen = set()
		for row in self.senders:
			row.sender_id = (row.sender_id or "").strip()
			key = (row.sender_id.upper(), row.match_type)
			if key in seen:
				frappe.throw(_("Row {0}: duplicate Sender ID {1}").format(row.idx, row.sender_id))
			seen.add(key)
			if row.match_type == "Contains" and len(row.sender_id) < 3:
				frappe.throw(
					_(
						"Row {0}: a 'Contains' sender must be at least 3 characters to avoid "
						"picking up unrelated messages"
					).format(row.idx)
				)

	def validate_patterns(self):
		for row in self.patterns:
			try:
				compiled = re.compile(row.regex or "")
			except re.error as e:
				frappe.throw(_("Pattern row {0}: invalid regex ({1})").format(row.idx, e))
			if "amount" not in compiled.groupindex:
				frappe.throw(
					_("Pattern row {0}: the regex needs a named group (?P&lt;amount&gt;...)").format(row.idx)
				)
		if self.parser == PARSER_CUSTOM and not any(p.enabled for p in self.patterns):
			frappe.throw(_("Add at least one enabled pattern when the parser is 'Custom Patterns Only'."))

	def set_bank(self):
		if self.bank:
			return
		settings = frappe.get_cached_doc("SMS Ledger Settings")
		if not settings.auto_create_bank:
			return
		from sms_ledger.parsers.base import detect_bank
		from sms_ledger.posting import ensure_bank

		# "KCB" -> "KCB Bank", so it is the same Bank record that counterparty
		# detection creates from other messages
		self.bank = ensure_bank(detect_bank(self.source_name) or self.source_name)
