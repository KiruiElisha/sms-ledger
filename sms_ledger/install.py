import frappe

DEVICE_ROLE = "SMS Ledger Device"


def ensure_role():
	if not frappe.db.exists("Role", DEVICE_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": DEVICE_ROLE,
				"desk_access": 0,
				"description": "Phone app that sends SMS alerts to SMS Ledger",
			}
		).insert(ignore_permissions=True)


def after_install():
	ensure_role()
	create_default_sources()


def create_default_sources():
	"""Disabled starter sources. Set the Ledger Account on each and enable it."""
	defaults = [
		{
			"source_name": "M-Pesa",
			"parser": "M-Pesa",
			"senders": [{"sender_id": "MPESA", "match_type": "Exact"}],
			"must_contain": "confirmed",
			"must_not_contain": "",
			"match_names": "M-PESA\nMPESA\nSafaricom",
		},
		{
			"source_name": "KCB",
			"parser": "Bank Alert",
			"senders": [{"sender_id": "KCB", "match_type": "Exact"}],
			"must_contain": "",
			"must_not_contain": "otp\none time pin\nloan limit\npassword",
			"match_names": "KCB\nKCB Bank\nKCB Paybill\nKCB Paybill AC",
		},
	]
	for d in defaults:
		if frappe.db.exists("SMS Source", d["source_name"]):
			continue
		doc = frappe.get_doc({"doctype": "SMS Source", "enabled": 0, **d})
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_permissions = True
		doc.bank = None
		try:
			doc.insert()
		except Exception:
			frappe.log_error(title=f"SMS Ledger: could not create default source {d['source_name']}")
