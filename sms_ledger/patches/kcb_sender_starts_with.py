"""KCB alerts arrive under more than one sender name (KCB, KCB_BANK...). The starter source only
matched "KCB" exactly, so the others were never read."""

import frappe


def execute():
	frappe.db.set_value(
		"SMS Source Sender",
		{"parent": "KCB", "parenttype": "SMS Source", "sender_id": "KCB", "match_type": "Exact"},
		"match_type",
		"Starts With",
	)
	frappe.cache.delete_value("sms_ledger:sources")
