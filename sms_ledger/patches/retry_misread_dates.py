"""Messages whose date was misread (e.g. 2001) failed with "not in any active Fiscal Year". Back to Pending, so
the hourly job posts them again with the corrected date."""

import frappe


def execute():
	frappe.db.sql(
		"""update `tabSMS Transaction` set status = 'Pending'
		where status = 'Failed' and error like %s""",
		("%not in any active Fiscal Year%",),
	)
