"""Parser tests. Run without a bench:

    cd apps/sms_ledger && python -m unittest sms_ledger.tests.test_parsers -v

or inside a bench:  bench --site <site> run-tests --module sms_ledger.tests.test_parsers
"""

import unittest
from datetime import datetime

from sms_ledger.parsers import PARSER_BANK, PARSER_MPESA, message_hash, normalize_phone, parse_message


def mp(body):
	return parse_message(body, PARSER_MPESA)


class TestMpesa(unittest.TestCase):
	def test_received(self):
		t = mp(
			"TJK3ABC12D Confirmed.You have received Ksh1,500.00 from JOHN DOE 0712345678 on 20/10/25 "
			"at 3:15 PM  New M-PESA balance is Ksh12,345.67. Earn interest daily on Ziidi MMF,Dial *334#"
		)
		self.assertEqual(t.reference, "TJK3ABC12D")
		self.assertEqual(t.direction, "In")
		self.assertEqual(t.transaction_type, "Received")
		self.assertEqual(t.amount, 1500.0)
		self.assertEqual(t.counterparty, "JOHN DOE")
		self.assertEqual(t.counterparty_phone, "0712345678")
		self.assertEqual(t.balance, 12345.67)
		self.assertEqual(t.transaction_datetime, datetime(2025, 10, 20, 15, 15))

	def test_received_masked_phone(self):
		t = mp(
			"UAB1CDE2FG Confirmed.You have received Ksh250.00 from MARY WANJIKU 2547******678 on 3/1/26 at 9:05 AM "
			"New M-PESA balance is Ksh900.00."
		)
		self.assertEqual(t.counterparty, "MARY WANJIKU")
		self.assertEqual(t.counterparty_phone, "2547******678")

	def test_received_from_bank(self):
		t = mp(
			"TJK3ABC12E Confirmed.You have received Ksh10,000.00 from KCB 1234567 on 21/10/25 at 10:00 AM "
			"New M-PESA balance is Ksh20,000.00."
		)
		self.assertEqual(t.counterparty, "KCB")
		self.assertEqual(t.counterparty_bank, "KCB Bank")
		self.assertEqual(t.counterparty_account, "1234567")
		self.assertIsNone(t.counterparty_phone)

	def test_received_from_kcb_drops_the_paybill_digits_from_the_name(self):
		t = mp(
			"UJQIGBPD21 Confirmed.You have received Ksh2,000.00 from KCB 1 501901 on 26/10/26 at 9:46 AM "
			"New M-PESA balance is Ksh2,028.97. See all your balances now https://saf.cx/kWQpy."
		)
		self.assertEqual(
			(t.counterparty, t.counterparty_bank, t.counterparty_account), ("KCB", "KCB Bank", "501901")
		)
		self.assertEqual((t.amount, t.balance), (2000.0, 2028.97))

	def test_sent_to_a_name_without_a_number(self):
		t = mp(
			"UJRIGBTXTO Confirmed. Ksh30.00 sent to LAMECK  OKEMWA on 27/10/26 at 10:13 AM. New M-PESA balance "
			"is Ksh1,151.97. Transaction cost, Ksh0.00. Amount you can transact within the day is 499,820.00."
		)
		self.assertEqual(
			(t.direction, t.amount, t.charges, t.counterparty), ("Out", 30.0, 0.0, "LAMECK OKEMWA")
		)
		self.assertEqual(t.transaction_datetime, datetime(2026, 10, 27, 10, 13))

	def test_sent(self):
		t = mp(
			"TJK3ABC12F Confirmed. Ksh1,000.00 sent to JANE DOE 0722000000 on 20/10/25 at 10:01 AM. "
			"New M-PESA balance is Ksh5,000.00. Transaction cost, Ksh13.00. Amount you can transact within the day is 498,000.00."
		)
		self.assertEqual(
			(t.direction, t.transaction_type, t.amount, t.charges), ("Out", "Sent", 1000.0, 13.0)
		)
		self.assertEqual(t.counterparty, "JANE DOE")
		self.assertEqual(t.counterparty_phone, "0722000000")

	def test_paybill(self):
		t = mp(
			"TJK3ABC12G Confirmed. Ksh2,000.00 sent to KPLC PREPAID for account 12345678901 on 20/10/25 at 9:00 AM "
			"New M-PESA balance is Ksh3,000.00. Transaction cost, Ksh33.00.Amount you can transact within the day is 499,000.00."
		)
		self.assertEqual(t.transaction_type, "Paybill")
		self.assertEqual(t.counterparty, "KPLC PREPAID")
		self.assertEqual(t.counterparty_account, "12345678901")
		self.assertEqual(t.charges, 33.0)

	def test_paybill_to_bank(self):
		t = mp(
			"TJK3ABC12H Confirmed. Ksh5,000.00 sent to KCB Paybill AC for account 1234567890123 on 22/10/25 at 8:10 AM "
			"New M-PESA balance is Ksh1,000.00. Transaction cost, Ksh34.00."
		)
		self.assertEqual(t.counterparty_bank, "KCB Bank")
		self.assertEqual(t.counterparty_account, "1234567890123")

	def test_buy_goods(self):
		t = mp(
			"TJK3ABC12J Confirmed. Ksh350.00 paid to NAIVAS SUPERMARKET. on 20/10/25 at 1:22 PM.New M-PESA balance is "
			"Ksh2,650.00. Transaction cost, Ksh0.00. Amount you can transact within the day is 499,650.00."
		)
		self.assertEqual(
			(t.transaction_type, t.counterparty, t.amount), ("Buy Goods", "NAIVAS SUPERMARKET", 350.0)
		)

	def test_withdraw(self):
		t = mp(
			"TJK3ABC12K Confirmed.on 20/10/25 at 4:00 PMWithdraw Ksh2,000.00 from 123456 - JOHN AGENT SHOP Kasarani "
			"New M-PESA balance is Ksh1,000.00. Transaction cost, Ksh29.00."
		)
		self.assertEqual(
			(t.transaction_type, t.direction, t.amount, t.charges), ("Withdrawal", "Out", 2000.0, 29.0)
		)
		self.assertEqual(t.counterparty_account, "123456")
		self.assertEqual(t.counterparty, "JOHN AGENT SHOP Kasarani")
		self.assertEqual(t.transaction_datetime, datetime(2025, 10, 20, 16, 0))

	def test_deposit(self):
		t = mp(
			"TJK3ABC12L Confirmed. On 20/10/25 at 11:00 AM Give Ksh5,000.00 cash to MAMA MBOGA AGENT New M-PESA balance is Ksh6,000.00."
		)
		self.assertEqual((t.transaction_type, t.direction, t.amount), ("Deposit", "In", 5000.0))

	def test_airtime(self):
		t = mp(
			"TJK3ABC12M confirmed.You bought Ksh100.00 of airtime on 20/10/25 at 8:00 AM.New M-PESA balance is Ksh900.00. Transaction cost, Ksh0.00."
		)
		self.assertEqual((t.transaction_type, t.direction, t.amount), ("Airtime", "Out", 100.0))

	def test_mshwari(self):
		t = mp(
			"TJK3ABC12N Confirmed.Ksh500.00 transferred to M-Shwari account on 20/10/25 at 2:00 PM. M-PESA balance is Ksh400.00 .New M-Shwari saving account balance is Ksh1,500.00."
		)
		self.assertEqual(
			(t.transaction_type, t.direction, t.counterparty), ("Transfer Out", "Out", "M-Shwari")
		)
		t = mp(
			"TJK3ABC12P Confirmed.Ksh300.00 transferred from M-Shwari account on 21/10/25 at 2:00 PM. M-Shwari balance is Ksh1,200.00 .M-PESA balance is Ksh700.00 ."
		)
		self.assertEqual((t.transaction_type, t.direction, t.amount), ("Transfer In", "In", 300.0))

	def test_reversal(self):
		t = mp(
			"TJK3ABC12Q Confirmed. Reversal of transaction TJK3ABC12F has been successfully reversed on 20/10/25 at 5:00 PM "
			"and Ksh1,000.00 is credited to your M-PESA account. New M-PESA balance is Ksh6,000.00."
		)
		self.assertEqual(
			(t.transaction_type, t.direction, t.related_reference), ("Reversal", "In", "TJK3ABC12F")
		)

	def test_ignored(self):
		self.assertIsNone(
			mp("Failed. You do not have enough money in your M-PESA account to send Ksh5,000.00.")
		)
		self.assertIsNone(mp("Your Fuliza M-PESA limit has been increased to Ksh2,000."))
		self.assertIsNone(mp("Y'ello! Dial *334# for great offers."))


class TestBankAlerts(unittest.TestCase):
	def test_credit(self):
		t = parse_message(
			"Dear JOHN, your KCB A/C ****4521 has been credited with KES 5,000.00 from JANE WAMBUI on "
			"20/10/2025 at 10:15 AM. Ref: FT25293XYZ12. Avail Bal KES 25,300.50",
			PARSER_BANK,
		)
		self.assertEqual((t.direction, t.amount, t.balance), ("In", 5000.0, 25300.5))
		self.assertEqual(t.reference, "FT25293XYZ12")
		self.assertEqual(t.counterparty, "JANE WAMBUI")
		self.assertEqual(t.account_hint, "****4521")
		self.assertEqual(t.transaction_datetime, datetime(2025, 10, 20, 10, 15))

	def test_debit_with_charges(self):
		t = parse_message(
			"KES 2,000.00 has been debited from your account 1234XXXX4521 on 21-10-2025 14:02 to EQUITY BANK "
			"via Pesalink. Charges KES 50.00. Ref 8822ABCD. Bal KES 23,250.50",
			PARSER_BANK,
		)
		self.assertEqual((t.direction, t.amount, t.charges, t.balance), ("Out", 2000.0, 50.0, 23250.5))
		self.assertEqual(t.counterparty_bank, "Equity Bank")
		self.assertEqual(t.reference, "8822ABCD")

	def test_credit_from_mpesa_keeps_code(self):
		t = parse_message(
			"Your account ****4521 has been credited with KES 5,000.00 from MPESA. MPESA Ref TJK3ABC12H "
			"on 22/10/2025. Avail Bal KES 30,000.00",
			PARSER_BANK,
		)
		self.assertEqual(t.related_reference, "TJK3ABC12H")
		self.assertEqual(t.direction, "In")

	def test_kcb_send_to_mpesa_keeps_both_codes(self):
		t = parse_message(
			"MBNHE3TF7P9589O2  KES 2,000.00 sent from 128****079 to 254****381 - ELISHA KIPKEMOI KIRUI on "
			"2026-10-26 09:46:06 AM. M-PESA REF: UJQIGBPD21",
			PARSER_BANK,
		)
		self.assertEqual((t.direction, t.amount), ("Out", 2000.0))
		self.assertEqual((t.reference, t.related_reference), ("MBNHE3TF7P9589O2", "UJQIGBPD21"))
		self.assertEqual((t.counterparty, t.counterparty_phone), ("ELISHA KIPKEMOI KIRUI", "254****381"))
		self.assertEqual(t.account_hint, "128****079")
		self.assertEqual(t.transaction_datetime, datetime(2026, 10, 26, 9, 46, 6))
		self.assertIsNone(t.notice)

	def test_kcb_notice_to_the_recipient_is_marked_as_a_notice(self):
		t = parse_message(
			"MBNHE3TF7P9589O2 Confirmed.  KES 2,000.00 received from ELISHA KIPKEMOI KIRUI - 128****079 on "
			"2026-10-26 09:46:06 AM via KCB.",
			PARSER_BANK,
		)
		self.assertEqual(t.reference, "MBNHE3TF7P9589O2")
		self.assertIn("Notice to the recipient", t.notice)

	def test_no_money(self):
		self.assertIsNone(
			parse_message("Dear customer, your KCB loan limit is now available. Dial *522#", PARSER_BANK)
		)


class TestCustomPattern(unittest.TestCase):
	def test_custom_pattern_first(self):
		patterns = [
			{
				"regex": r"Txn (?P<reference>\w+): (?P<party>.+?) paid KES (?P<amount>[\d,.]+) on (?P<date>\d{2}/\d{2}/\d{4})",
				"direction": "In",
				"transaction_type": "Custom",
			}
		]
		t = parse_message(
			"Txn ABC123: PETER OTIENO paid KES 750.00 on 05/10/2026 to your till", PARSER_BANK, patterns
		)
		self.assertEqual((t.reference, t.counterparty, t.amount), ("ABC123", "PETER OTIENO", 750.0))
		self.assertEqual(t.transaction_datetime, datetime(2026, 10, 5))


class TestHelpers(unittest.TestCase):
	def test_hash_ignores_whitespace(self):
		self.assertEqual(message_hash("MPESA", "a  b\nc"), message_hash("mpesa ", "a b c"))

	def test_phone(self):
		self.assertEqual(normalize_phone("0712 345 678"), "254712345678")
		self.assertEqual(normalize_phone("+254712345678"), "254712345678")


if __name__ == "__main__":
	unittest.main()
