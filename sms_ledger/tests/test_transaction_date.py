"""The message's own date is used when it is plausible; a misread one gives way to when the phone received it."""

import unittest
from datetime import datetime

from sms_ledger.posting import transaction_date

RECEIVED = datetime(2026, 10, 30, 22, 15)


class TestTransactionDate(unittest.TestCase):
	def test_the_date_in_the_message_is_kept_when_it_is_near_when_the_phone_received_it(self):
		paid = datetime(2026, 10, 30, 21, 58)
		self.assertEqual(transaction_date(paid, RECEIVED), paid)

	def test_a_misread_date_years_away_falls_back_to_when_the_phone_received_it(self):
		self.assertEqual(transaction_date(datetime(2001, 9, 25), RECEIVED), RECEIVED)

	def test_a_message_without_a_date_uses_when_the_phone_received_it(self):
		self.assertEqual(transaction_date(None, RECEIVED), RECEIVED)

	def test_an_old_message_synced_late_keeps_its_own_date(self):
		received_in_june = datetime(2026, 6, 2, 9, 0)
		self.assertEqual(
			transaction_date(datetime(2026, 6, 1, 18, 0), received_in_june), datetime(2026, 6, 1, 18, 0)
		)
