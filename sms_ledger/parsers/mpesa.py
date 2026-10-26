"""Safaricom M-PESA confirmation message parser.

Handles the common confirmation formats:
  received, send money, paybill, buy goods (till), agent withdrawal, agent
  deposit, airtime, M-Shwari / KCB M-PESA / savings transfers, reversals.

Anything without a transaction code + "Confirmed" (failed transactions,
Fuliza notices, promos, balance queries) returns None and is ignored.
"""

from __future__ import annotations

import re

from .base import (
	AIRTIME,
	BUY_GOODS,
	DEPOSIT,
	IN,
	OUT,
	PAYBILL,
	RECEIVED,
	REVERSAL,
	SENT,
	TRANSFER_IN,
	TRANSFER_OUT,
	WITHDRAWAL,
	ParsedTransaction,
	clean_name,
	detect_bank,
	normalize_text,
	parse_amount,
	parse_datetime,
	split_name_and_number,
)

F = re.IGNORECASE | re.DOTALL

KSH = r"(?:Ksh|KES)\s?"
NUM = r"([\d,]+(?:\.\d{1,2})?)"
ON_DATE = r"\s*on\s*\d{1,2}/\d{1,2}/\d{2,4}"

CODE_RE = re.compile(r"\b([A-Z0-9]{10})\b\.?\s*[Cc]onfirmed")
DATE_RE = re.compile(r"on\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*at\s*(\d{1,2}:\d{2}\s*[AP]\.?M\.?)", F)
BALANCE_RE = re.compile(r"(?:M-?PESA|Account|Utility)\s*balance\s*(?:is|was)?\s*:?\s*" + KSH + NUM, F)
COST_RE = re.compile(r"Transaction\s*cost,?\s*" + KSH + NUM, F)

# order matters: most specific first
REVERSAL_RE = re.compile(
	r"Reversal\s*of\s*transaction\s*([A-Z0-9]{10}).*?" + KSH + NUM + r"\s*is\s*(credited|debited)", F
)
TRANSFER_TO_RE = re.compile(
	KSH + NUM + r"\s*(?:has\s*been\s*)?transferred\s*to\s*(.+?)\s*account" + ON_DATE, F
)
TRANSFER_FROM_RE = re.compile(
	KSH + NUM + r"\s*(?:has\s*been\s*)?transferred\s*from\s*(.+?)\s*account" + ON_DATE, F
)
RECEIVED_RE = re.compile(r"You\s*have\s*received\s*" + KSH + NUM + r"\s*from\s*(.+?)" + ON_DATE, F)
RECEIVED_BIZ_RE = re.compile(KSH + NUM + r"\s*received\s*from\s*(.+?)" + ON_DATE, F)
PAYBILL_RE = re.compile(KSH + NUM + r"\s*sent\s*to\s*(.+?)\s*for\s*account\s*(.+?)" + ON_DATE, F)
SENT_RE = re.compile(KSH + NUM + r"\s*sent\s*to\s*(.+?)" + ON_DATE, F)
PAID_RE = re.compile(KSH + NUM + r"\s*paid\s*to\s*(.+?)" + ON_DATE, F)
WITHDRAW_RE = re.compile(r"Withdraw\s*" + KSH + NUM + r"\s*from\s*(.+?)\s*New\s*M-?PESA", F)
DEPOSIT_RE = re.compile(r"Give\s*" + KSH + NUM + r"\s*cash\s*to\s*(.+?)\s*New\s*M-?PESA", F)
AIRTIME_RE = re.compile(
	r"(?:You\s*)?bought\s*" + KSH + NUM + r"\s*of\s*airtime(?:\s*for\s*(\+?\d{9,12}))?", F
)


def parse(body: str) -> ParsedTransaction | None:
	text = normalize_text(body)

	code_m = CODE_RE.search(text)
	if not code_m:
		return None
	reference = code_m.group(1).upper()

	date_m = DATE_RE.search(text)
	txn_dt = parse_datetime(date_m.group(1), date_m.group(2).replace(".", "")) if date_m else None
	bal_m = BALANCE_RE.search(text)
	balance = parse_amount(bal_m.group(1)) if bal_m else None
	cost_m = COST_RE.search(text)
	charges = parse_amount(cost_m.group(1)) if cost_m else 0.0

	def build(direction, ttype, amount, **kw) -> ParsedTransaction:
		return ParsedTransaction(
			direction=direction,
			transaction_type=ttype,
			amount=parse_amount(amount) or 0.0,
			reference=reference,
			charges=charges or 0.0,
			balance=balance,
			transaction_datetime=txn_dt,
			**kw,
		)

	if m := REVERSAL_RE.search(text):
		direction = IN if m.group(3).lower() == "credited" else OUT
		return build(
			direction,
			REVERSAL,
			m.group(2),
			related_reference=m.group(1).upper(),
			counterparty="M-PESA Reversal",
		)

	if m := TRANSFER_TO_RE.search(text):
		target = clean_name(m.group(2))
		return build(
			OUT, TRANSFER_OUT, m.group(1), counterparty=target, counterparty_bank=detect_bank(target)
		)

	if m := TRANSFER_FROM_RE.search(text):
		src = clean_name(m.group(2))
		return build(IN, TRANSFER_IN, m.group(1), counterparty=src, counterparty_bank=detect_bank(src))

	if m := (RECEIVED_RE.search(text) or RECEIVED_BIZ_RE.search(text)):
		name, number = split_name_and_number(m.group(2))
		bank = detect_bank(name)
		kw = {"counterparty": clean_name(name), "counterparty_bank": bank}
		if number:
			# bank-to-mpesa messages put an account/ref number where a phone would be
			if bank or not re.match(r"^(?:\+?254|0)[17]", number):
				kw["counterparty_account"] = number
			else:
				kw["counterparty_phone"] = number
		return build(IN, RECEIVED, m.group(1), **kw)

	if m := PAYBILL_RE.search(text):
		name = clean_name(m.group(2))
		return build(
			OUT,
			PAYBILL,
			m.group(1),
			counterparty=name,
			counterparty_account=clean_name(m.group(3)),
			counterparty_bank=detect_bank(name),
		)

	if m := SENT_RE.search(text):
		name, number = split_name_and_number(m.group(2))
		bank = detect_bank(name)
		kw = {"counterparty": clean_name(name), "counterparty_bank": bank}
		if number:
			if bank or not re.match(r"^(?:\+?254|0)[17]", number):
				kw["counterparty_account"] = number
			else:
				kw["counterparty_phone"] = number
		return build(OUT, SENT, m.group(1), **kw)

	if m := PAID_RE.search(text):
		return build(OUT, BUY_GOODS, m.group(1), counterparty=clean_name(m.group(2)))

	if m := WITHDRAW_RE.search(text):
		agent = clean_name(m.group(2))
		agent_no = None
		if agent and (am := re.match(r"^(\d{4,})\s*-\s*(.+)$", agent)):
			agent_no, agent = am.group(1), clean_name(am.group(2))
		return build(OUT, WITHDRAWAL, m.group(1), counterparty=agent, counterparty_account=agent_no)

	if m := DEPOSIT_RE.search(text):
		return build(IN, DEPOSIT, m.group(1), counterparty=clean_name(m.group(2)))

	if m := AIRTIME_RE.search(text):
		return build(
			OUT, AIRTIME, m.group(1), counterparty="Safaricom Airtime", counterparty_phone=m.group(2)
		)

	return None
