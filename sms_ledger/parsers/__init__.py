"""Parser registry.

parse_message() tries, in order:
  1. the source's custom regex patterns (SMS Source > Patterns table)
  2. the built-in parser chosen on the source (M-Pesa / Bank Alert)
"""

from __future__ import annotations

import re

from . import bank, mpesa
from .base import (
	CUSTOM,
	IN,
	OUT,
	TRANSACTION_TYPES,
	ParsedTransaction,
	clean_name,
	detect_bank,
	message_hash,
	normalize_phone,
	normalize_text,
	parse_amount,
	parse_datetime,
	split_name_and_number,
)

PARSER_MPESA = "M-Pesa"
PARSER_BANK = "Bank Alert"
PARSER_CUSTOM = "Custom Patterns Only"

BUILTIN = {
	PARSER_MPESA: mpesa.parse,
	PARSER_BANK: bank.parse,
}

__all__ = [
	"IN",
	"OUT",
	"PARSER_BANK",
	"PARSER_CUSTOM",
	"PARSER_MPESA",
	"TRANSACTION_TYPES",
	"ParsedTransaction",
	"message_hash",
	"normalize_phone",
	"parse_message",
]


def _apply_pattern(text: str, pattern: dict) -> ParsedTransaction | None:
	"""pattern = {"regex", "direction", "transaction_type"}.

	Supported named groups: amount (required), reference, party, phone,
	account, bank, balance, charges, date, time, related_reference."""
	try:
		m = re.search(pattern["regex"], text, re.IGNORECASE | re.DOTALL)
	except re.error:
		return None
	if not m:
		return None
	g = {k: v for k, v in m.groupdict().items() if v}
	amount = parse_amount(g.get("amount"))
	if not amount:
		return None

	direction = pattern.get("direction") or IN
	if direction == "Detect":
		low = text.lower()
		direction = OUT if re.search(r"debited|sent|paid|withdraw", low) else IN

	party, number = split_name_and_number(g.get("party"))
	return ParsedTransaction(
		direction=direction,
		transaction_type=pattern.get("transaction_type") or CUSTOM,
		amount=amount,
		reference=(g.get("reference") or "").upper() or None,
		related_reference=(g.get("related_reference") or "").upper() or None,
		charges=parse_amount(g.get("charges")) or 0.0,
		balance=parse_amount(g.get("balance")),
		counterparty=clean_name(party),
		counterparty_phone=g.get("phone")
		or (number if number and re.match(r"^(?:\+?254|0)[17]", number) else None),
		counterparty_account=g.get("account")
		or (number if number and not re.match(r"^(?:\+?254|0)[17]", number) else None),
		counterparty_bank=detect_bank(g.get("bank") or party),
		transaction_datetime=parse_datetime(g.get("date"), g.get("time")),
	)


def parse_message(
	body: str, parser: str = PARSER_MPESA, custom_patterns: list[dict] | None = None
) -> ParsedTransaction | None:
	text = normalize_text(body)
	for pattern in custom_patterns or []:
		if result := _apply_pattern(text, pattern):
			return result
	fn = BUILTIN.get(parser)
	return fn(text) if fn else None
