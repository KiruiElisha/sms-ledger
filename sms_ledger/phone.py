"""What the phone app shows: the month's money, the activity feed, and fixing a message.

GET  sms_ledger.phone.dashboard      {month: "2026-10"}
GET  sms_ledger.phone.activity       {start, page_length, status}
GET  sms_ledger.phone.accounts
POST sms_ledger.phone.retry          {name}
POST sms_ledger.phone.recategorise   {name, account, remember}

Same access as the upload API: the SMS Ledger Device role, or an accounts manager.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_first_day, get_last_day, getdate, nowdate

from sms_ledger.api import _check_access
from sms_ledger.posting import process_transaction

IN, OUT = "In", "Out"
NEEDS_ATTENTION = ("Failed", "Unparsed")
FEED_FIELDS = [
	"name",
	"source",
	"status",
	"direction",
	"transaction_type",
	"amount",
	"charges",
	"counterparty",
	"reference",
	"transaction_date",
	"offset_account",
	"is_transfer",
	"error",
	"message",
]


def _month_range(month: str | None):
	first = get_first_day(getdate(f"{month}-01") if month else nowdate())
	return first, get_last_day(first)


def _counted(first, last) -> list[dict]:
	"""Money that moved this month, each transfer once (its linked side is skipped)."""
	return frappe.get_all(
		"SMS Transaction",
		filters={"status": "Posted", "transaction_date": ["between", [first, f"{last} 23:59:59"]]},
		fields=[
			"direction",
			"amount",
			"charges",
			"is_transfer",
			"counterparty",
			"offset_account",
			"transaction_date",
		],
	)


def _totals(rows: list[dict]) -> dict:
	money_in = sum(flt(r.amount) for r in rows if r.direction == IN and not r.is_transfer)
	money_out = sum(flt(r.amount) for r in rows if r.direction == OUT and not r.is_transfer)
	charges = sum(flt(r.charges) for r in rows)
	return {"in": money_in, "out": money_out, "charges": charges, "net": money_in - money_out - charges}


def _daily(rows: list[dict], last, days: int = 14) -> list[dict]:
	end = min(getdate(last), getdate(nowdate()))
	series = {str(add_days(end, -i)): {"in": 0.0, "out": 0.0} for i in range(days - 1, -1, -1)}
	for r in rows:
		day = str(getdate(r.transaction_date))
		if day in series and not r.is_transfer:
			series[day]["in" if r.direction == IN else "out"] += flt(r.amount)
	return [{"date": d, **v} for d, v in series.items()]


def _top(rows: list[dict], key: str, limit: int = 5) -> list[dict]:
	"""Where the money went: spending grouped by payee or by account."""
	spent: dict[str, float] = {}
	for r in rows:
		if r.direction == OUT and not r.is_transfer and r.get(key):
			spent[r[key]] = spent.get(r[key], 0.0) + flt(r.amount)
	ranked = sorted(spent.items(), key=lambda kv: kv[1], reverse=True)[:limit]
	return [{"label": label, "amount": amount} for label, amount in ranked]


def _balances(last) -> list[dict]:
	"""Each source's balance as its latest message up to the month's end stated it."""
	out = []
	for source in frappe.get_all("SMS Source", filters={"enabled": 1}, pluck="name"):
		latest = frappe.get_all(
			"SMS Transaction",
			filters={"source": source, "balance": [">", 0], "transaction_date": ["<=", f"{last} 23:59:59"]},
			fields=["balance", "transaction_date"],
			order_by="transaction_date desc",
			limit=1,
		)
		if latest:
			out.append(
				{
					"source": source,
					"balance": flt(latest[0].balance),
					"as_of": str(latest[0].transaction_date),
				}
			)
	return out


@frappe.whitelist(methods=["GET"])
def dashboard(month: str | None = None) -> dict:
	_check_access()
	first, last = _month_range(month)
	rows = _counted(first, last)
	return {
		"month": str(first)[:7],
		"currency": frappe.db.get_default("currency") or "KES",
		"totals": _totals(rows),
		"daily": _daily(rows, last),
		"top_payees": _top(rows, "counterparty"),
		"top_accounts": _top(rows, "offset_account"),
		"balances": _balances(last),
		"attention": frappe.db.count("SMS Transaction", {"status": ["in", NEEDS_ATTENTION]}),
	}


@frappe.whitelist(methods=["GET"])
def activity(start=0, page_length=30, status: str | None = None) -> list[dict]:
	_check_access()
	filters = {"status": ["in", NEEDS_ATTENTION]} if status == "attention" else {}
	if status and status != "attention":
		filters["status"] = status
	return frappe.get_all(
		"SMS Transaction",
		filters=filters,
		fields=FEED_FIELDS,
		order_by="transaction_date desc, creation desc",
		start=cint(start),
		page_length=min(cint(page_length) or 30, 100),
	)


@frappe.whitelist(methods=["GET"])
def accounts() -> list[dict]:
	"""Income and expense accounts a message can be filed under."""
	_check_access()
	company = frappe.db.get_single_value("SMS Ledger Settings", "company")
	return frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"root_type": ["in", ["Income", "Expense"]],
		},
		fields=["name", "account_name", "root_type"],
		order_by="root_type asc, account_name asc",
	)


def _summary(name: str) -> dict:
	return frappe.get_all("SMS Transaction", filters={"name": name}, fields=FEED_FIELDS)[0]


@frappe.whitelist(methods=["POST"])
def retry(name: str) -> dict:
	_check_access()
	process_transaction(name, force=True)
	return _summary(name)


@frappe.whitelist(methods=["POST"])
def recategorise(name: str, account: str, remember: int = 0) -> dict:
	"""File a message under another account, re-posting it; optionally for this payee from now on."""
	_check_access()
	if frappe.db.get_value("Account", account, "root_type") not in ("Income", "Expense"):
		frappe.throw(_("Pick an income or expense account"))
	txn = frappe.get_doc("SMS Transaction", name)
	txn.use_manual_values = 1
	txn.offset_account = account
	txn.flags.ignore_permissions = True
	txn.save()
	if cint(remember) and txn.counterparty:
		_remember(txn, account)
	process_transaction(name, force=True)
	return _summary(name)


def _remember(txn, account: str):
	rule = {
		"match_field": "Counterparty",
		"match_type": "Equals",
		"match_value": txn.counterparty,
		"direction": txn.direction,
	}
	if existing := frappe.db.get_value("SMS Ledger Rule", rule, "name"):
		frappe.db.set_value("SMS Ledger Rule", existing, "account", account)
	else:
		doc = frappe.get_doc(
			{
				**rule,
				"doctype": "SMS Ledger Rule",
				"rule_name": f"{txn.counterparty} ({txn.direction})"[:140],
				"enabled": 1,
				"priority": 5,
			}
		)
		doc.update({"action": "Post", "account": account})
		doc.insert(ignore_permissions=True)
	frappe.cache.delete_value("sms_ledger:rules")
