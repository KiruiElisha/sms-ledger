"""HTTP API used by the phone app (and the desk buttons).

Phone app authentication: token auth of an ERPNext user that has the
"SMS Ledger Device" role.
    Authorization: token <api_key>:<api_secret>

GET  /api/method/sms_ledger.api.get_config
POST /api/method/sms_ledger.api.ingest   {"device_id": "...", "messages": [
        {"id": "<phone row id>", "sender": "MPESA", "body": "...", "timestamp": 1729500000000}, ...]}
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import frappe
from frappe import _
from frappe.utils import cint, convert_utc_to_system_timezone, now_datetime

from sms_ledger.parsers import message_hash, parse_message
from sms_ledger.posting import get_sources, process_transaction

DEVICE_ROLE = "SMS Ledger Device"
ALLOWED_ROLES = {DEVICE_ROLE, "System Manager", "Accounts Manager"}
MAX_BATCH = 500


def _check_access():
	if frappe.session.user == "Guest" or not ALLOWED_ROLES.intersection(frappe.get_roles()):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _norm_sender(value: str) -> str:
	return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def match_source(sender: str, body: str):
	"""First enabled source whose sender IDs and keyword filters accept this message."""
	s = _norm_sender(sender)
	low = (body or "").lower()
	for src in get_sources():
		ok = False
		for row in src.senders:
			sid = _norm_sender(row["sender_id"])
			if not sid:
				continue
			mt = row.get("match_type") or "Exact"
			if (
				(mt == "Exact" and s == sid)
				or (mt == "Starts With" and s.startswith(sid))
				or (mt == "Contains" and sid in s)
			):
				ok = True
				break
		if not ok:
			continue
		if src.must_contain and not any(k in low for k in src.must_contain):
			continue
		if src.must_not_contain and any(k in low for k in src.must_not_contain):
			continue
		return src
	return None


def _to_system_datetime(timestamp_ms) -> datetime | None:
	try:
		ts = int(timestamp_ms) / 1000.0
	except (TypeError, ValueError):
		return None
	utc = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
	return convert_utc_to_system_timezone(utc).replace(tzinfo=None)


@frappe.whitelist(methods=["GET", "POST"])
def get_config():
	_check_access()
	settings = frappe.get_cached_doc("SMS Ledger Settings")
	return {
		"enabled": cint(settings.enabled),
		"sync_days_back": cint(settings.sync_days_back) or 30,
		"server_time": str(now_datetime()),
		"user": frappe.session.user,
		"sources": [
			{
				"source": s.name,
				"senders": [
					{"sender_id": r["sender_id"], "match_type": r.get("match_type") or "Exact"}
					for r in s.senders
				],
			}
			for s in get_sources()
		],
	}


@frappe.whitelist(methods=["POST"])
def ingest(messages=None, device_id=None):
	_check_access()
	messages = frappe.parse_json(messages) if isinstance(messages, str) else (messages or [])
	if not isinstance(messages, list):
		frappe.throw(_("messages must be a list"))
	if len(messages) > MAX_BATCH:
		frappe.throw(_("Send at most {0} messages per request").format(MAX_BATCH))

	results, new_names = [], []
	for m in messages:
		m = frappe._dict(m or {})
		sender, body = (m.sender or "").strip(), (m.body or "").strip()
		if not sender or not body:
			results.append({"id": m.id, "status": "invalid"})
			continue
		source = match_source(sender, body)
		if not source:
			results.append({"id": m.id, "status": "skipped"})
			continue

		h = message_hash(sender, body)
		existing = frappe.db.get_value("SMS Transaction", {"message_hash": h}, "name")
		if existing:
			results.append({"id": m.id, "status": "duplicate", "name": existing})
			continue

		frappe.db.savepoint("sms_ingest")
		received_at = _to_system_datetime(m.timestamp) or now_datetime()
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SMS Transaction",
					"source": source.name,
					"sender": sender[:140],
					"message": body,
					"message_hash": h,
					"received_at": received_at,
					# the SMS's own date replaces this once parsed; until then the feed sorts by arrival
					"transaction_date": received_at,
					"device_id": (device_id or m.device_id or "")[:140],
					"status": "Pending",
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
		except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
			frappe.db.rollback(save_point="sms_ingest")
			results.append(
				{
					"id": m.id,
					"status": "duplicate",
					"name": frappe.db.get_value("SMS Transaction", {"message_hash": h}, "name"),
				}
			)
			continue
		new_names.append(doc.name)
		results.append({"id": m.id, "status": "accepted", "name": doc.name})

	if new_names:
		frappe.enqueue(
			"sms_ledger.posting.process_transactions",
			queue="short",
			names=new_names,
			enqueue_after_commit=True,
			timeout=1500,
		)

	return {
		"accepted": len(new_names),
		"duplicates": sum(1 for r in results if r["status"] == "duplicate"),
		"skipped": sum(1 for r in results if r["status"] in ("skipped", "invalid")),
		"results": results,
	}


@frappe.whitelist()
def reprocess(name: str):
	"""Desk button. Cancels any entries already made for this message and runs it again."""
	frappe.has_permission("SMS Transaction", "write", doc=name, throw=True)
	if not frappe.has_permission("Journal Entry", "cancel"):
		frappe.throw(_("You need permission to cancel Journal Entries to re-process."))
	txn = process_transaction(name, force=True)
	return {"status": txn.status if txn else None, "error": txn.error if txn else None}


@frappe.whitelist()
def process_selected(names):
	"""List-view action: process Pending / Parsed / Failed messages."""
	names = frappe.parse_json(names) if isinstance(names, str) else names
	frappe.has_permission("SMS Transaction", "write", throw=True)
	done = []
	for name in names or []:
		status = frappe.db.get_value("SMS Transaction", name, "status")
		if status in ("Pending", "Parsed", "Failed", "Unparsed"):
			txn = process_transaction(name, force=True)
			done.append({"name": name, "status": txn.status if txn else None})
	return done


@frappe.whitelist()
def test_parse(source: str, message: str, sender: str | None = None):
	"""SMS Source 'Test Message' button: shows what the parser extracts, without saving."""
	frappe.has_permission("SMS Source", "read", doc=source, throw=True)
	src = frappe.get_doc("SMS Source", source)
	patterns = [
		{"regex": p.regex, "direction": p.direction, "transaction_type": p.transaction_type}
		for p in src.patterns
		if p.enabled
	]
	parsed = parse_message(message, src.parser, patterns)
	accepted_by = None
	if sender:
		match = match_source(sender, message)
		accepted_by = match.name if match else None
	return {
		"parsed": parsed.as_dict() if parsed else None,
		"accepted_by_source": accepted_by,
	}
