"""Messages that were never parsed had no transaction date, so the phone's feed could not sort them
with a plain field (newer Frappe refuses SQL expressions in order_by)."""

import frappe


def execute():
	frappe.db.sql(
		"""update `tabSMS Transaction` set transaction_date = coalesce(received_at, creation)
		where transaction_date is null"""
	)
