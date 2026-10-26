"""Shared types and helpers for SMS parsers.

This module deliberately has no Frappe imports so the parsers can be unit
tested with plain `python -m unittest`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime

# --------------------------------------------------------------------------
# Transaction types (kept in sync with the "Transaction Type" select options
# on the SMS Transaction / SMS Ledger Rule doctypes)
# --------------------------------------------------------------------------
RECEIVED = "Received"
SENT = "Sent"
PAYBILL = "Paybill"
BUY_GOODS = "Buy Goods"
WITHDRAWAL = "Withdrawal"
DEPOSIT = "Deposit"
AIRTIME = "Airtime"
TRANSFER_IN = "Transfer In"
TRANSFER_OUT = "Transfer Out"
REVERSAL = "Reversal"
BANK_CREDIT = "Bank Credit"
BANK_DEBIT = "Bank Debit"
CUSTOM = "Custom"

TRANSACTION_TYPES = [
	RECEIVED,
	SENT,
	PAYBILL,
	BUY_GOODS,
	WITHDRAWAL,
	DEPOSIT,
	AIRTIME,
	TRANSFER_IN,
	TRANSFER_OUT,
	REVERSAL,
	BANK_CREDIT,
	BANK_DEBIT,
	CUSTOM,
]

IN = "In"
OUT = "Out"

# Kenyan banks / institutions, used to detect a counterparty bank inside a
# message (e.g. "sent to EQUITY BANK for account 0123...").
# key = canonical Bank name created in ERPNext, values = lowercase aliases
KNOWN_BANKS: dict[str, list[str]] = {
	"KCB Bank": ["kcb"],
	"Equity Bank": ["equity"],
	"Co-operative Bank": ["co-op", "coop", "co-operative", "cooperative"],
	"NCBA Bank": ["ncba"],
	"Absa Bank": ["absa", "barclays"],
	"Stanbic Bank": ["stanbic"],
	"Standard Chartered Bank": ["standard chartered", "stanchart"],
	"I&M Bank": ["i&m", "i & m", "im bank"],
	"Diamond Trust Bank": ["dtb", "diamond trust"],
	"Family Bank": ["family bank"],
	"Sidian Bank": ["sidian"],
	"Kingdom Bank": ["kingdom bank"],
	"Prime Bank": ["prime bank"],
	"Bank of Africa": ["bank of africa", "boa kenya"],
	"Credit Bank": ["credit bank"],
	"Gulf African Bank": ["gulf african"],
	"National Bank": ["national bank"],
	"HFC": ["hfc", "housing finance"],
	"Faulu Microfinance Bank": ["faulu"],
	"Kenya Women Microfinance Bank": ["kwft"],
	"Stima Sacco": ["stima sacco"],
	"Safaricom M-Pesa": ["m-pesa", "mpesa"],
	"Airtel Money": ["airtel money"],
}


@dataclass
class ParsedTransaction:
	direction: str  # "In" (money into the source) / "Out"
	transaction_type: str
	amount: float
	reference: str | None = None
	charges: float = 0.0
	balance: float | None = None
	counterparty: str | None = None
	counterparty_phone: str | None = None
	counterparty_account: str | None = None  # paybill account, till, agent no, bank a/c
	counterparty_bank: str | None = None  # canonical bank name from KNOWN_BANKS
	transaction_datetime: datetime | None = None
	related_reference: str | None = None  # e.g. original code of a reversal
	account_hint: str | None = None  # masked own account from bank alerts ("****4521")

	def as_dict(self) -> dict:
		d = asdict(self)
		if self.transaction_datetime:
			d["transaction_datetime"] = self.transaction_datetime.strftime("%Y-%m-%d %H:%M:%S")
		return d


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
	return _WS.sub(" ", (text or "").replace(" ", " ")).strip()


def message_hash(sender: str, body: str) -> str:
	"""Stable fingerprint of a message, independent of the device timestamp, so
	the same SMS read from the inbox twice (or from the live receiver and the
	inbox scan) always produces the same hash."""
	raw = f"{(sender or '').strip().upper()}|{normalize_text(body)}"
	return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_amount(value: str | None) -> float | None:
	if value is None:
		return None
	value = value.strip().rstrip(".").replace(",", "").replace(" ", "")
	if not value:
		return None
	try:
		return round(float(value), 2)
	except ValueError:
		return None


_DATE_FORMATS = [
	"%d/%m/%y",
	"%d/%m/%Y",
	"%d-%m-%Y",
	"%d-%m-%y",
	"%Y-%m-%d",
	"%d.%m.%Y",
	"%d.%m.%y",
	"%d-%b-%Y",
	"%d-%b-%y",
	"%d %b %Y",
	"%d %B %Y",
	"%d%b%Y",
	"%d/%b/%Y",
]
_TIME_FORMATS = ["%I:%M %p", "%I:%M%p", "%H:%M", "%H:%M:%S", "%I:%M:%S %p"]


def parse_datetime(date_str: str | None, time_str: str | None = None) -> datetime | None:
	if not date_str:
		return None
	date_str = normalize_text(date_str).rstrip(".,")
	time_str = normalize_text(time_str or "").upper().rstrip(".,")
	parsed_date = None
	for fmt in _DATE_FORMATS:
		try:
			parsed_date = datetime.strptime(date_str, fmt)
			break
		except ValueError:
			continue
	if not parsed_date:
		return None
	if time_str:
		for fmt in _TIME_FORMATS:
			try:
				t = datetime.strptime(time_str, fmt)
				return parsed_date.replace(hour=t.hour, minute=t.minute, second=t.second)
			except ValueError:
				continue
	return parsed_date


PHONE_RE = re.compile(r"(?:\+?254|0)\s?[17][\d\*xX]{8}")


def normalize_phone(phone: str | None) -> str | None:
	"""07XXXXXXXX / +2547XXXXXXXX / 2547XXXXXXXX -> 2547XXXXXXXX.
	Masked numbers (with * or X) are returned as-is: they can be shown but
	not used to match a contact."""
	if not phone:
		return None
	p = re.sub(r"[\s\-]", "", phone).lstrip("+")
	if p.startswith("0") and len(p) == 10:
		p = "254" + p[1:]
	return p


def is_masked(value: str | None) -> bool:
	return bool(value) and bool(re.search(r"[\*xX]", value))


_TRAILING_NUMBER = re.compile(
	r"^(?P<name>.*?)[\s\-,]*(?P<num>\+?[\d\*xX]{6,}|(?:\+?254|0)[17][\d\*xX]{8})?[\s.]*$"
)


def split_name_and_number(text: str | None) -> tuple[str | None, str | None]:
	"""'JOHN DOE 0712345678' -> ('JOHN DOE', '0712345678')
	'123456 - SHOP NAME' stays as name (number is in front, handled by callers)."""
	if not text:
		return None, None
	text = normalize_text(text).strip(" .,-")
	m = _TRAILING_NUMBER.match(text)
	if m and m.group("num") and m.group("name"):
		return m.group("name").strip(" .,-") or None, m.group("num")
	return text or None, None


def clean_name(name: str | None) -> str | None:
	if not name:
		return None
	name = normalize_text(name).strip(" .,-:;")
	return name or None


def detect_bank(text: str | None) -> str | None:
	if not text:
		return None
	low = f" {text.lower()} "
	for canonical, aliases in KNOWN_BANKS.items():
		for alias in aliases:
			if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", low):
				return canonical
	return None


AMOUNT = r"(?:Ksh|KES|KSH|Kshs)\.?\s?([\d,]+(?:\.\d{1,2})?)"
