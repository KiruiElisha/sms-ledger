"""Turns SMS Transactions into ERPNext accounting entries.

Flow per message:  parse -> de-duplicate -> classify (rules / defaults /
transfer detection) -> find the other side of a transfer -> post.
"""

from __future__ import annotations

import re
import string

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime

from sms_ledger.parsers import IN, OUT, normalize_phone, parse_message
from sms_ledger.parsers.base import (
	AIRTIME,
	DEPOSIT,
	REVERSAL,
	TRANSFER_IN,
	TRANSFER_OUT,
	WITHDRAWAL,
	is_masked,
)

DONE = ("Posted", "Linked")
PARTY_NAME_FIELD = {"Customer": "customer_name", "Supplier": "supplier_name", "Employee": "employee_name"}


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------
def process_transactions(names: list[str]):
	"""Background job: process a batch in the order the messages arrived, so an
	original transaction is always posted before its reversal."""
	if not names:
		return
	ordered = frappe.get_all(
		"SMS Transaction",
		filters={"name": ["in", names]},
		pluck="name",
		order_by="transaction_date asc, received_at asc, creation asc",
	)
	for name in ordered:
		process_transaction(name)
		frappe.db.commit()


def process_pending():
	"""Hourly: catch anything a background job missed."""
	names = frappe.get_all("SMS Transaction", filters={"status": "Pending"}, pluck="name", limit=500)
	process_transactions(names)


def process_transaction(name: str, force: bool = False):
	settings = frappe.get_cached_doc("SMS Ledger Settings")
	if not settings.enabled or not settings.company:
		return None  # stays Pending until SMS Ledger Settings is filled in

	txn = frappe.get_doc("SMS Transaction", name)
	if txn.status in DONE and not force:
		return txn

	frappe.db.savepoint("sms_ledger_txn")
	try:
		if txn.status in DONE:
			undo_posting(txn)
			unlink_counterpart(txn)

		source = frappe.get_cached_doc("SMS Source", txn.source)
		if not parse_into(txn, source):
			_save(txn)
			return txn

		if dup := duplicate_of(txn):
			txn.status = "Ignored"
			txn.error = _("Duplicate of {0} (same reference)").format(dup)
			_save(txn)
			return txn

		classify(txn, settings, source)
		if txn.status == "Ignored":
			_save(txn)
			return txn

		if not cint(settings.auto_post) and not force:
			txn.status = "Parsed"
			txn.error = None
			_save(txn)
			return txn

		txn.error = None
		post(txn, settings, source)
		_save(txn)
	except Exception:
		frappe.db.rollback(save_point="sms_ledger_txn")
		txn.reload()
		txn.status = "Failed"
		txn.error = frappe.get_traceback()[-2000:]
		_save(txn)
		frappe.log_error(
			title=f"SMS Ledger: {name} failed", reference_doctype="SMS Transaction", reference_name=name
		)
	return txn


def _save(txn):
	txn.flags.ignore_permissions = True
	txn.flags.ignore_validate_update_after_submit = True
	txn.save()


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def parse_into(txn, source) -> bool:
	patterns = [
		{"regex": p.regex, "direction": p.direction, "transaction_type": p.transaction_type}
		for p in source.patterns
		if p.enabled
	]
	parsed = parse_message(txn.message, source.parser, patterns)
	if not parsed or not parsed.amount:
		txn.status = "Unparsed" if _looks_financial(txn.message) else "Ignored"
		txn.error = _("No transaction found in this message")
		return False

	if (
		source.account_mask
		and parsed.account_hint
		and not _same_account(source.account_mask, parsed.account_hint)
	):
		txn.status = "Ignored"
		txn.error = _("Message is for account {0}, not {1}").format(parsed.account_hint, source.account_mask)
		return False

	settings = frappe.get_cached_doc("SMS Ledger Settings")
	txn.update(
		{
			"reference": parsed.reference,
			"related_reference": parsed.related_reference,
			"transaction_type": parsed.transaction_type,
			"direction": parsed.direction,
			"amount": parsed.amount,
			"charges": parsed.charges or 0,
			"balance": parsed.balance,
			"account_hint": parsed.account_hint,
			"counterparty": _display_name(parsed.counterparty, settings),
			"counterparty_phone": parsed.counterparty_phone,
			"counterparty_account": parsed.counterparty_account,
			"transaction_date": parsed.transaction_datetime or txn.received_at or now_datetime(),
		}
	)
	if parsed.counterparty_bank:
		txn.counterparty_bank = ensure_bank(parsed.counterparty_bank)
	return True


def _looks_financial(message: str) -> bool:
	return bool(re.search(r"(ksh|kes)\s?[\d,]+", message or "", re.IGNORECASE))


def _tail_digits(value: str) -> str:
	m = re.search(r"(\d+)\D*$", value or "")
	return m.group(1) if m else ""


def _same_account(mask: str, hint: str) -> bool:
	a, b = _tail_digits(mask), _tail_digits(hint)
	if not a or not b:
		return True  # nothing comparable: don't reject
	n = min(len(a), len(b), 4)
	return a[-n:] == b[-n:]


def _display_name(name: str | None, settings) -> str | None:
	if not name:
		return None
	name = name.strip()[:140]
	return string.capwords(name) if cint(settings.title_case_names) else name


def duplicate_of(txn) -> str | None:
	if not txn.reference:
		return None
	return frappe.db.get_value(
		"SMS Transaction",
		{
			"source": txn.source,
			"reference": txn.reference,
			"name": ["!=", txn.name],
			"status": ["not in", ["Ignored", "Unparsed"]],
		},
	)


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
def classify(txn, settings, source):
	"""Fills offset_account / party / posting_mode / is_transfer / rule."""
	if cint(txn.use_manual_values) and (txn.offset_account or txn.party):
		txn.is_transfer = 1 if txn.offset_account and _is_bank_or_cash(txn.offset_account) else 0
		txn.posting_mode = txn.posting_mode or settings.default_posting_mode
		return

	txn.rule = None
	txn.party_type = txn.party = txn.offset_account = None
	txn.is_transfer = 0
	txn.posting_mode = settings.default_posting_mode or "Journal Entry"

	rule = match_rule(txn)
	if rule:
		txn.rule = rule.name
		if rule.action == "Ignore":
			txn.status = "Ignored"
			txn.error = _("Ignored by rule {0}").format(rule.name)
			return
		txn.offset_account = rule.account
		txn.party_type = rule.party_type or None
		txn.party = rule.party or None
		txn.posting_mode = rule.posting_mode or txn.posting_mode
		if rule.account and _is_bank_or_cash(rule.account):
			txn.is_transfer = 1
			txn.party_type = txn.party = None
			return
		if not txn.party:
			set_party(txn, settings)
		if not txn.offset_account:
			txn.offset_account = _default_account(txn, settings)
		return

	# reversal: undo the original's classification
	if txn.transaction_type == REVERSAL and txn.related_reference:
		orig = frappe.db.get_value(
			"SMS Transaction",
			{"source": txn.source, "reference": txn.related_reference},
			["offset_account", "party_type", "party", "is_transfer"],
			as_dict=True,
		)
		if orig and orig.offset_account:
			txn.update(
				{
					"offset_account": orig.offset_account,
					"party_type": orig.party_type,
					"party": orig.party,
					"is_transfer": orig.is_transfer,
					"posting_mode": "Journal Entry",
				}
			)
			return
	if txn.transaction_type == REVERSAL:
		# original not on file: money back reduces expenses, money taken back reduces income
		txn.offset_account = (
			settings.default_expense_account if txn.direction == IN else settings.default_income_account
		)
		txn.posting_mode = "Journal Entry"
		return

	# transfer to / from another of your configured sources
	if target := find_target_source(txn, source):
		txn.is_transfer = 1
		txn.offset_account = target.account
		return

	ttype = txn.transaction_type
	if ttype in (WITHDRAWAL, DEPOSIT) and settings.cash_account:
		txn.is_transfer = 1
		txn.offset_account = settings.cash_account
		return
	if ttype in (TRANSFER_IN, TRANSFER_OUT) and settings.savings_transfer_account:
		txn.is_transfer = 1
		txn.offset_account = settings.savings_transfer_account
		return
	if ttype == AIRTIME:
		txn.offset_account = settings.airtime_account or settings.default_expense_account
		txn.posting_mode = "Journal Entry"
		return

	set_party(txn, settings)
	txn.offset_account = _default_account(txn, settings)


def _default_account(txn, settings):
	return settings.default_income_account if txn.direction == IN else settings.default_expense_account


def _is_bank_or_cash(account) -> bool:
	return frappe.get_cached_value("Account", account, "account_type") in ("Bank", "Cash")


def _get_rules():
	rules = frappe.cache.get_value("sms_ledger:rules")
	if rules is None:
		rules = frappe.get_all(
			"SMS Ledger Rule",
			filters={"enabled": 1},
			fields=[
				"name",
				"priority",
				"source",
				"direction",
				"transaction_type",
				"match_field",
				"match_type",
				"match_value",
				"action",
				"account",
				"posting_mode",
				"party_type",
				"party",
				"cost_center",
			],
			order_by="priority desc, creation asc",
		)
		frappe.cache.set_value("sms_ledger:rules", rules)
	return [frappe._dict(r) for r in rules]


def match_rule(txn):
	field_map = {
		"Counterparty": txn.counterparty,
		"Counterparty Account": txn.counterparty_account,
		"Counterparty Phone": txn.counterparty_phone,
		"Message": txn.message,
	}
	for rule in _get_rules():
		if rule.source and rule.source != txn.source:
			continue
		if rule.direction and rule.direction != txn.direction:
			continue
		if rule.transaction_type and rule.transaction_type != txn.transaction_type:
			continue
		value = (field_map.get(rule.match_field) or "").strip()
		target = (rule.match_value or "").strip()
		if not value or not target:
			continue
		if rule.match_field == "Counterparty Phone":
			value, target = normalize_phone(value) or value, normalize_phone(target) or target
		low_v, low_t = value.lower(), target.lower()
		if rule.match_type == "Equals" and low_v == low_t:
			return rule
		if rule.match_type == "Contains" and low_t in low_v:
			return rule
		if rule.match_type == "Starts With" and low_v.startswith(low_t):
			return rule
		if rule.match_type == "Regex":
			try:
				if re.search(target, value, re.IGNORECASE):
					return rule
			except re.error:
				continue
	return None


# ---------------------------------------------------------------------------
# sources / transfers
# ---------------------------------------------------------------------------
def get_sources():
	data = frappe.cache.get_value("sms_ledger:sources")
	if data is None:
		data = []
		for name in frappe.get_all("SMS Source", filters={"enabled": 1}, pluck="name"):
			doc = frappe.get_doc("SMS Source", name)
			names = {doc.source_name.lower()}
			if doc.bank:
				names.add(doc.bank.lower())
			names.update(x.strip().lower() for x in (doc.match_names or "").splitlines() if x.strip())
			data.append(
				{
					"name": doc.name,
					"account": doc.account,
					"account_mask": doc.account_mask,
					"names": sorted(names),
					"senders": [{"sender_id": s.sender_id, "match_type": s.match_type} for s in doc.senders],
					"must_contain": [
						x.strip().lower() for x in (doc.must_contain or "").splitlines() if x.strip()
					],
					"must_not_contain": [
						x.strip().lower() for x in (doc.must_not_contain or "").splitlines() if x.strip()
					],
				}
			)
		frappe.cache.set_value("sms_ledger:sources", data)
	return [frappe._dict(d) for d in data]


def _mentions(text: str | None, names: list[str]) -> bool:
	if not text:
		return False
	low = f" {text.lower()} "
	return any(re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", low) for n in names if n)


def find_target_source(txn, source):
	"""Is this message a transfer to / from another of YOUR configured sources?"""
	for other in get_sources():
		if other.name == source.name or not other.account:
			continue
		if not (
			_mentions(txn.counterparty, other.names)
			or (txn.counterparty_bank and txn.counterparty_bank.lower() in other.names)
		):
			continue
		if txn.transaction_type in (TRANSFER_IN, TRANSFER_OUT):
			return other
		# paybill to a bank: only a transfer if the account number is yours
		if (
			other.account_mask
			and txn.counterparty_account
			and _same_account(other.account_mask, txn.counterparty_account)
		):
			return other
	return None


def find_counterpart(txn, source, settings):
	"""The same money seen from the other account (e.g. M-PESA 'sent to KCB'
	and KCB 'credited from MPESA')."""
	days = cint(settings.transfer_match_days)
	if not txn.amount or not txn.transaction_date:
		return None
	dt = get_datetime(txn.transaction_date)
	candidates = frappe.get_all(
		"SMS Transaction",
		filters={
			"name": ["!=", txn.name],
			"source": ["!=", txn.source],
			"direction": OUT if txn.direction == IN else IN,
			"amount": flt(txn.amount),
			"status": ["in", ["Parsed", "Posted", "Pending"]],
			"linked_transaction": ["is", "not set"],
			"transaction_date": ["between", [add_days(dt, -days), add_days(dt, days)]],
		},
		fields=[
			"name",
			"source",
			"reference",
			"related_reference",
			"message",
			"counterparty",
			"status",
			"is_transfer",
			"offset_account",
		],
		order_by="transaction_date asc",
	)
	if not candidates:
		return None

	sources = {s.name: s for s in get_sources()}
	me = sources.get(source.name)
	for c in candidates:
		other = sources.get(c.source)
		if not other or not me:
			continue
		refs_match = any(r and r in (c.message or "") for r in (txn.reference, txn.related_reference)) or any(
			r and r in (txn.message or "") for r in (c.reference, c.related_reference)
		)
		i_name_them = _mentions(txn.counterparty, other.names) or (
			txn.is_transfer and txn.offset_account == other.account
		)
		they_name_me = _mentions(c.counterparty, me.names) or (
			c.is_transfer and c.offset_account == me.account
		)
		if (
			refs_match
			or (i_name_them and they_name_me)
			or ((i_name_them and not c.counterparty) or (they_name_me and not txn.counterparty))
		):
			return frappe._dict(c, other=other)
	return None


# ---------------------------------------------------------------------------
# posting
# ---------------------------------------------------------------------------
def post(txn, settings, source):
	counterpart = find_counterpart(txn, source, settings)
	if counterpart:
		return post_transfer_pair(txn, counterpart, settings, source)

	if (
		txn.is_transfer
		or not txn.party
		or txn.posting_mode != "Payment Entry"
		or txn.party_type not in ("Customer", "Supplier", "Employee")
	):
		txn.journal_entry = make_journal_entry(txn, settings, source)
	else:
		txn.payment_entry = make_payment_entry(txn, settings, source)
		if flt(txn.charges):
			txn.charges_entry = make_charges_entry(txn, settings, source)

	create_party_bank_account(txn)
	txn.status = "Posted"


def post_transfer_pair(txn, counterpart, settings, source):
	other_doc = frappe.get_doc("SMS Transaction", counterpart.name)
	other_source = frappe.get_cached_doc("SMS Source", other_doc.source)

	already_transfer = (
		other_doc.status == "Posted" and other_doc.is_transfer and other_doc.offset_account == source.account
	)

	if already_transfer:
		# the other side already moved the money; only our charges are left
		txn.is_transfer = 1
		txn.offset_account = other_source.account
		txn.party_type = txn.party = None
		if flt(txn.charges):
			txn.charges_entry = make_charges_entry(txn, settings, source)
		_link(txn, other_doc)
		txn.status = "Linked"
		txn.error = _("Transfer already recorded by {0}").format(other_doc.name)
		return

	if other_doc.status == "Posted":
		if not cint(settings.auto_fix_transfer_duplicates):
			# leave both as they are; just post ours normally
			txn.journal_entry = make_journal_entry(txn, settings, source)
			txn.status = "Posted"
			txn.error = _("Possible transfer with {0}; auto-fix is off").format(other_doc.name)
			return
		undo_posting(other_doc)

	# we post the transfer, the other side becomes 'Linked' (keeps its own charges)
	txn.is_transfer = 1
	txn.offset_account = other_source.account
	txn.party_type = txn.party = None
	txn.journal_entry = make_journal_entry(txn, settings, source)

	other_doc.is_transfer = 1
	other_doc.offset_account = source.account
	other_doc.party_type = other_doc.party = None
	if flt(other_doc.charges):
		other_doc.charges_entry = make_charges_entry(other_doc, settings, other_source)
	other_doc.status = "Linked"
	other_doc.error = _("Transfer recorded by {0}").format(txn.name)
	_link(txn, other_doc)
	_save(other_doc)
	txn.status = "Posted"


def _link(a, b):
	a.linked_transaction = b.name
	b.linked_transaction = a.name
	frappe.db.set_value("SMS Transaction", b.name, "linked_transaction", a.name, update_modified=False)


def unlink_counterpart(txn):
	"""Before re-processing one side of a transfer, put the other side back to
	'Parsed' so the pair is rebuilt from scratch."""
	other_name = txn.linked_transaction
	txn.linked_transaction = None
	if not other_name or not frappe.db.exists("SMS Transaction", other_name):
		return
	other = frappe.get_doc("SMS Transaction", other_name)
	other.linked_transaction = None
	if other.status == "Linked":
		undo_posting(other)
		other.status = "Parsed"
		other.error = _("Unlinked while {0} was re-processed").format(txn.name)
	_save(other)


def undo_posting(txn):
	for fieldname, doctype in (
		("journal_entry", "Journal Entry"),
		("payment_entry", "Payment Entry"),
		("charges_entry", "Journal Entry"),
	):
		name = txn.get(fieldname)
		if not name or not frappe.db.exists(doctype, name):
			txn.set(fieldname, None)
			continue
		doc = frappe.get_doc(doctype, name)
		doc.flags.ignore_permissions = True
		if doc.docstatus == 1:
			doc.cancel()
		elif doc.docstatus == 0:
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		txn.set(fieldname, None)
	txn.status = "Pending"


def _cost_center(txn, settings):
	if txn.rule:
		cc = frappe.db.get_value("SMS Ledger Rule", txn.rule, "cost_center")
		if cc:
			return cc
	return settings.cost_center or frappe.get_cached_value("Company", settings.company, "cost_center")


def _row(account, debit=0.0, credit=0.0, cost_center=None, party_type=None, party=None):
	row = {
		"account": account,
		"debit_in_account_currency": flt(debit, 2),
		"credit_in_account_currency": flt(credit, 2),
		"cost_center": cost_center,
	}
	account_type = frappe.get_cached_value("Account", account, "account_type")
	if party and account_type in ("Receivable", "Payable"):
		row.update({"party_type": party_type, "party": party})
		if (party_type == "Customer" and credit) or (party_type == "Supplier" and debit):
			row["is_advance"] = "Yes"
	return row


def _remark(txn, source):
	parts = [f"{source.name} {txn.transaction_type or ''} {txn.reference or ''}".strip()]
	if txn.counterparty:
		parts.append(txn.counterparty)
	if txn.counterparty_account:
		parts.append(f"A/C {txn.counterparty_account}")
	parts.append(f"[{txn.name}]")
	parts.append(txn.message or "")
	return "\n".join(parts)[:2000]


def _new_je(txn, settings, voucher_type, remark):
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = voucher_type
	je.company = settings.company
	je.posting_date = getdate(txn.transaction_date)
	je.cheque_no = (txn.reference or txn.name)[:140]
	je.cheque_date = je.posting_date
	je.pay_to_recd_from = (txn.counterparty or "")[:140] or None
	je.user_remark = remark
	je.flags.ignore_permissions = True
	return je


def _finish(doc, settings):
	doc.insert(ignore_permissions=True)
	if cint(settings.submit_entries):
		doc.submit()
	return doc.name


def make_journal_entry(txn, settings, source):
	if not txn.offset_account:
		frappe.throw(_("No offset account could be determined"))
	amount, charges = flt(txn.amount, 2), flt(txn.charges, 2)
	cc = _cost_center(txn, settings)
	src = source.account
	party_type = txn.party_type if not txn.is_transfer else None
	party = txn.party if not txn.is_transfer else None

	je = _new_je(txn, settings, "Contra Entry" if txn.is_transfer else "Bank Entry", _remark(txn, source))
	if txn.direction == IN:
		je.append("accounts", _row(src, debit=amount, cost_center=cc))
		je.append(
			"accounts",
			_row(txn.offset_account, credit=amount, cost_center=cc, party_type=party_type, party=party),
		)
		if charges:
			je.append("accounts", _row(settings.charges_account, debit=charges, cost_center=cc))
			je.append("accounts", _row(src, credit=charges, cost_center=cc))
	else:
		je.append(
			"accounts",
			_row(txn.offset_account, debit=amount, cost_center=cc, party_type=party_type, party=party),
		)
		if charges:
			je.append("accounts", _row(settings.charges_account, debit=charges, cost_center=cc))
		je.append("accounts", _row(src, credit=amount + charges, cost_center=cc))
	return _finish(je, settings)


def make_charges_entry(txn, settings, source):
	charges = flt(txn.charges, 2)
	cc = _cost_center(txn, settings)
	je = _new_je(txn, settings, "Bank Entry", _("Charges: ") + _remark(txn, source))
	je.append("accounts", _row(settings.charges_account, debit=charges, cost_center=cc))
	je.append("accounts", _row(source.account, credit=charges, cost_center=cc))
	return _finish(je, settings)


def make_payment_entry(txn, settings, source):
	from erpnext.accounts.party import get_party_account

	party_account = get_party_account(txn.party_type, txn.party, settings.company)
	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive" if txn.direction == IN else "Pay"
	pe.company = settings.company
	pe.posting_date = getdate(txn.transaction_date)
	pe.party_type = txn.party_type
	pe.party = txn.party
	if pe.payment_type == "Receive":
		pe.paid_from, pe.paid_to = party_account, source.account
	else:
		pe.paid_from, pe.paid_to = source.account, party_account
	pe.paid_amount = pe.received_amount = flt(txn.amount, 2)
	pe.source_exchange_rate = pe.target_exchange_rate = 1
	pe.reference_no = (txn.reference or txn.name)[:140]
	pe.reference_date = pe.posting_date
	pe.cost_center = _cost_center(txn, settings)
	pe.remarks = _remark(txn, source)
	if source.bank_account:
		pe.bank_account = source.bank_account
	pe.flags.ignore_permissions = True
	pe.setup_party_account_field()
	pe.set_missing_values()
	txn.offset_account = party_account
	return _finish(pe, settings)


# ---------------------------------------------------------------------------
# parties & banks
# ---------------------------------------------------------------------------
def set_party(txn, settings):
	if not txn.counterparty:
		return
	party_type = settings.incoming_party_type if txn.direction == IN else settings.outgoing_party_type
	party_type = party_type or ("Customer" if txn.direction == IN else "Supplier")
	party = get_or_create_party(party_type, txn.counterparty, txn.counterparty_phone, settings)
	if party:
		txn.party_type, txn.party = party_type, party


def _phone_variants(phone: str | None) -> list[str]:
	if not phone or is_masked(phone):
		return []
	p = normalize_phone(phone)
	if not p:
		return []
	out = {p}
	if p.startswith("254") and len(p) == 12:
		out.update({"0" + p[3:], "+" + p})
	return sorted(out)


def find_party_by_phone(party_type, phone):
	variants = _phone_variants(phone)
	if not variants:
		return None
	rows = frappe.db.sql(
		"""
		select dl.link_name
		from `tabContact Phone` cp
		join `tabDynamic Link` dl on dl.parent = cp.parent and dl.parenttype = 'Contact'
		where dl.link_doctype = %(party_type)s
			and replace(replace(replace(cp.phone, ' ', ''), '-', ''), '+', '') in %(variants)s
		limit 1
	""",
		{"party_type": party_type, "variants": tuple(v.lstrip("+") for v in variants)},
	)
	return rows[0][0] if rows else None


def get_or_create_party(party_type, name, phone, settings):
	party = find_party_by_phone(party_type, phone)
	if party:
		return party
	name_field = PARTY_NAME_FIELD.get(party_type)
	if not name_field:
		return None
	party = frappe.db.get_value(party_type, {name_field: name}) or (
		frappe.db.exists(party_type, name) and name
	)
	if party:
		return party
	if not cint(settings.auto_create_party) or party_type not in ("Customer", "Supplier"):
		return None

	looks_like_person = bool(re.fullmatch(r"[A-Za-z'\- ]+", name)) and 2 <= len(name.split()) <= 4
	if party_type == "Customer":
		doc = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Individual" if looks_like_person else "Company",
				"customer_group": settings.customer_group
				or frappe.db.get_single_value("Selling Settings", "customer_group")
				or frappe.db.get_value("Customer Group", {"is_group": 0}),
				"territory": settings.territory
				or frappe.db.get_single_value("Selling Settings", "territory")
				or frappe.db.get_value("Territory", {"is_group": 0}),
			}
		)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_type": "Individual" if looks_like_person else "Company",
				"supplier_group": settings.supplier_group
				or frappe.db.get_single_value("Buying Settings", "supplier_group")
				or frappe.db.get_value("Supplier Group", {"is_group": 0}),
			}
		)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert()

	if _phone_variants(phone):
		contact = frappe.get_doc({"doctype": "Contact", "first_name": name[:140]})
		contact.append("phone_nos", {"phone": normalize_phone(phone), "is_primary_mobile_no": 1})
		contact.append("links", {"link_doctype": party_type, "link_name": doc.name})
		contact.flags.ignore_permissions = True
		contact.insert()
	return doc.name


def ensure_bank(bank_name: str | None) -> str | None:
	if not bank_name:
		return None
	bank_name = bank_name.strip()[:140]
	if frappe.db.exists("Bank", bank_name):
		return bank_name
	existing = frappe.db.get_value("Bank", {"bank_name": bank_name})
	if existing:
		return existing
	if not cint(frappe.db.get_single_value("SMS Ledger Settings", "auto_create_bank")):
		return None
	doc = frappe.get_doc({"doctype": "Bank", "bank_name": bank_name})
	doc.insert(ignore_permissions=True)
	return doc.name


def create_party_bank_account(txn):
	"""Record the counterparty's bank account (e.g. a supplier paid to their
	Equity account) as a Bank Account on that party."""
	if not (txn.party and txn.counterparty_bank and txn.counterparty_account) or txn.is_transfer:
		return
	if is_masked(txn.counterparty_account) or len(re.sub(r"\D", "", txn.counterparty_account)) < 6:
		return
	if frappe.db.exists(
		"Bank Account",
		{
			"party_type": txn.party_type,
			"party": txn.party,
			"bank": txn.counterparty_bank,
			"bank_account_no": txn.counterparty_account,
		},
	):
		return
	try:
		frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": txn.party[:120],
				"bank": txn.counterparty_bank,
				"party_type": txn.party_type,
				"party": txn.party,
				"bank_account_no": txn.counterparty_account,
				"is_company_account": 0,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		pass
