"""Generic bank-alert parser (used for KCB and any other bank).

Banks don't publish their SMS templates and change wording often, so this
parser works from keywords instead of one fixed template:

  direction   credited / received / deposited  vs  debited / withdrawn / sent / paid
  amount      first KES/Ksh figure that isn't a balance, charge or fee
  balance     "Bal", "Avail Bal", "Balance is" + figure
  charges     "charge(s)", "fee", "cost" + figure
  reference   "Ref", "Ref No", "Reference", "Txn ID", "Transaction ID", or an
              M-PESA code mentioned in the message
  party       "from X" (credits) / "to X" (debits)
  own account "A/C ****1234", "account 1234XXXX5678"

If a bank's wording doesn't fit, add a regex on the SMS Source (Patterns
table) — custom patterns are always tried before this parser.
"""

from __future__ import annotations

import re

from .base import (
	BANK_CREDIT,
	BANK_DEBIT,
	IN,
	OUT,
	ParsedTransaction,
	clean_name,
	detect_bank,
	normalize_text,
	parse_amount,
	parse_datetime,
	split_name_and_number,
)

F = re.IGNORECASE

CUR = r"(?:KES|Ksh|KSH|Kshs|KShs)\.?\s?"
NUM = r"([\d,]+(?:\.\d{1,2})?)"
AMOUNT_RE = re.compile(CUR + NUM, F)

CREDIT_WORDS = re.compile(
	r"\b(credited|received|deposited|deposit\s+of|has\s+been\s+paid\s+into|incoming|cr\b)", F
)
DEBIT_WORDS = re.compile(
	r"\b(debited|withdrawn|withdrawal|sent\s+to|paid\s+to|payment\s+to|purchase|transferred\s+to|dr\b)", F
)

BALANCE_RE = re.compile(
	r"(?:avail(?:able)?\.?\s*|actual\s*|ledger\s*|new\s*|a/c\s*)?bal(?:ance)?\.?\s*(?:is|of)?\s*:?\s*"
	+ CUR
	+ NUM,
	F,
)
CHARGE_RE = re.compile(
	r"(?:charges?|fees?|transaction\s+cost|excise\s+duty)\s*(?:of|is|:)?\s*" + CUR + NUM, F
)
REF_RE = re.compile(
	r"(?:ref(?:erence)?\.?\s*(?:no\.?|number|code)?|txn\s*(?:id|ref)|transaction\s*(?:id|ref(?:erence)?|code)|"
	r"mpesa\s*(?:ref|code)|m-pesa\s*(?:ref|code))\s*[:#.\-]?\s*([A-Z0-9][A-Z0-9\-/]{4,})",
	F,
)
MPESA_CODE_RE = re.compile(r"\b([A-Z]{1,3}[A-Z0-9]{7,9})\b")
ACCOUNT_RE = re.compile(
	r"(?:a/c|acc(?:ount)?|acct)\.?\s*(?:no\.?|number)?\s*(?:ending\s*(?:in|with)?\s*)?:?\s*([\dXx\*]{3,}[\dXx\*\-]*)",
	F,
)

DATE_PATTERNS = [
	# 20/10/2025 at 3:15 PM | 20-10-2025 15:15 | 2025-10-20 15:15:00
	re.compile(
		r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\s*(?:at\s*)?(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AP]M)?)?", F
	),
	re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:at\s*)?(\d{1,2}:\d{2}(?::\d{2})?)?", F),
	# 20-Oct-2025 / 20 Oct 2025
	re.compile(
		r"(\d{1,2}[\s\-/][A-Za-z]{3,9}[\s\-/]\d{2,4})\s*(?:at\s*)?(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AP]M)?)?", F
	),
]

# "from JOHN DOE on ..." / "to JOHN DOE via ..."
PARTY_STOP = r"(?=\s+(?:on|ref|reference|via|at|for|through|using|in|into|txn|transaction|a/c|acc|account|bal|avail|is|has|date)\b|[.,;]|$)"
FROM_RE = re.compile(r"\bfrom\s+(.+?)" + PARTY_STOP, F)
TO_RE = re.compile(r"\b(?:to|paid\s+to|sent\s+to|payment\s+to)\s+(.+?)" + PARTY_STOP, F)
NOT_PARTY = re.compile(r"^(?:your|you|the|a/c|account|acc|ac|mobile|wallet|kes|ksh)\b", F)


def _first_amount(text: str) -> float | None:
	"""First currency figure that is not labelled as a balance / charge."""
	for m in AMOUNT_RE.finditer(text):
		before = text[max(0, m.start() - 30) : m.start()].lower()
		if re.search(r"bal(ance)?|charge|fee|cost|duty|limit", before):
			continue
		amount = parse_amount(m.group(1))
		if amount:
			return amount
	return None


def _party(text: str, direction: str) -> tuple[str | None, str | None]:
	regex = FROM_RE if direction == IN else TO_RE
	for m in regex.finditer(text):
		candidate = clean_name(m.group(1))
		if not candidate or NOT_PARTY.match(candidate):
			continue
		if re.fullmatch(r"[\d\s,.]+", candidate):  # just a number
			continue
		if AMOUNT_RE.match(candidate):
			continue
		return split_name_and_number(candidate)
	return None, None


def _datetime(text: str):
	for regex in DATE_PATTERNS:
		for m in regex.finditer(text):
			dt = parse_datetime(m.group(1), (m.group(2) or "").replace(".", ""))
			if dt:
				return dt
	return None


def parse(
	body: str, transaction_type_credit: str = BANK_CREDIT, transaction_type_debit: str = BANK_DEBIT
) -> ParsedTransaction | None:
	text = normalize_text(body)
	if not AMOUNT_RE.search(text):
		return None

	credit = CREDIT_WORDS.search(text)
	debit = DEBIT_WORDS.search(text)
	if credit and debit:
		# whichever keyword appears first describes the transaction
		direction = IN if credit.start() < debit.start() else OUT
	elif credit:
		direction = IN
	elif debit:
		direction = OUT
	else:
		return None

	amount = _first_amount(text)
	if not amount:
		return None

	bal_m = BALANCE_RE.search(text)
	charge_m = CHARGE_RE.search(text)
	ref_m = REF_RE.search(text)
	reference = ref_m.group(1).strip("-/.").upper() if ref_m else None
	related = None
	if not reference:
		code_m = MPESA_CODE_RE.search(text)
		if code_m and re.search(r"\d", code_m.group(1)):
			reference = code_m.group(1)
	if reference and re.fullmatch(r"[A-Z0-9]{10}", reference) and re.search(r"m-?pesa", text, F):
		# keep the M-PESA code so the matching M-PESA message can be paired
		related = reference

	acct_m = ACCOUNT_RE.search(text)
	party, number = _party(text, direction)

	return ParsedTransaction(
		direction=direction,
		transaction_type=transaction_type_credit if direction == IN else transaction_type_debit,
		amount=amount,
		reference=reference,
		related_reference=related,
		charges=parse_amount(charge_m.group(1)) or 0.0 if charge_m else 0.0,
		balance=parse_amount(bal_m.group(1)) if bal_m else None,
		counterparty=party,
		counterparty_phone=number if number and re.match(r"^(?:\+?254|0)[17]", number) else None,
		counterparty_account=number if number and not re.match(r"^(?:\+?254|0)[17]", number) else None,
		counterparty_bank=detect_bank(party),
		transaction_datetime=_datetime(text),
		account_hint=acct_m.group(1) if acct_m else None,
	)
