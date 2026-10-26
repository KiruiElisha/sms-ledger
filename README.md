# SMS Ledger

Reads M-PESA and bank SMS alerts (KCB and any other bank) from an Android phone and posts them to
ERPNext as accounting entries, so the money moving through your wallets and bank accounts shows up in
Profit and Loss, the General Ledger and bank reconciliation.

```
Android phone ──(new SMS + inbox scan)──▶ sms_ledger.api.ingest ──▶ SMS Transaction
                                                                       │ parse
                                                                       │ de-duplicate (message hash + reference)
                                                                       │ classify (rules → transfers → defaults)
                                                                       │ create missing Customer / Supplier / Bank
                                                                       ▼
                                                        Journal Entry  or  Payment Entry
```

Works on ERPNext v15 and v16.

## Install

```bash
cd ~/frappe-bench
bench get-app https://github.com/KiruiElisha/sms-ledger
bench --site <site> install-app sms_ledger
bench --site <site> migrate
```

Installing creates a **SMS Ledger Device** role and two disabled starter sources: **M-Pesa** and **KCB**.

## Set up (ERPNext)

1. **Accounts.** Make sure you have ledger accounts for each wallet / bank (account type *Bank*), e.g.
   `M-Pesa - SIL`, `KCB - SIL`, plus an income account, an expense account and a charges account
   (e.g. `Bank Charges - SIL`). Optional: `Cash - SIL` for agent withdrawals, `M-Shwari - SIL`, an airtime
   expense account.
2. **SMS Ledger Settings.** Company, default income / expense / charges accounts, and the optional ones above.
3. **SMS Source** (one per institution). For each starter source set the **Ledger Account**, check the
   **Sender IDs** match what your phone shows (open a real message: the sender is shown at the top), and
   tick **Enabled**.
   - *Message Must Contain / Must Not Contain* stop look-alike messages (promos, OTPs, loan offers) from
     being picked up.
   - *Your Account Number*: on the KCB source, put your account number (or the last 4 digits). Alerts for
     other accounts are ignored, and M-PESA paybill payments to that account are recognised as transfers
     instead of expenses.
   - *Also Known As*: how this account is named in other sources' messages (e.g. `KCB`, `KCB M-PESA`).
   - Use **Test Message** on the source to paste a real SMS and see exactly what is extracted.
   - Another bank: add a source with parser **Bank Alert**, its sender ID and keywords. If its wording
     isn't understood, add a regex under **Custom Patterns** (named groups: `amount` required; `reference`,
     `party`, `phone`, `account`, `bank`, `balance`, `charges`, `date`, `time` optional).
4. **Device user.** Create a User (e.g. `sms-device@yourco.com`), give it only the **SMS Ledger Device**
   role, then *Settings → API Access → Generate Keys*. Put the key and secret in the phone app.

## How messages are posted

| Message | Entry |
|---|---|
| Money received (M-PESA received, bank credit) | Dr Source account / Cr income account. Sender created as **Customer** |
| Money sent, paybill, till (buy goods), bank debit | Dr expense account / Cr Source account. Recipient created as **Supplier** |
| Transaction cost / bank charges | Dr charges account (same entry, or a separate one for Payment Entries) |
| Agent withdrawal / deposit | Transfer to / from the Cash account |
| M-Shwari, KCB M-PESA, savings transfers | Transfer to the matching source, else the Savings / Wallet Transfer account |
| Airtime | Airtime expense account |
| Reversal | Opposite of the original transaction's entry |
| Failed, Fuliza notices, promos, OTPs | Ignored |

**Journal Entry** (default) posts straight to income / expense, which is what Profit and Loss needs.
The party is created and linked on the SMS Transaction, and its name goes in *Pay To / Recd From*.
**Payment Entry** (per rule, or as default in settings) posts against the party's receivable / payable
so you can match it to invoices with *Payment Reconciliation*.

### Rules (SMS Ledger Rule)

Rules run before the defaults, highest priority first. Examples:

| Match | Action |
|---|---|
| Counterparty contains `KPLC` | Account `Electricity - SIL` |
| Counterparty contains `NAIVAS` | Account `Office Supplies - SIL` |
| Counterparty Phone equals `0712345678`, direction In | Party Type Customer, Party `John Doe`, Posting Mode Payment Entry |
| Counterparty contains `SAFARICOM HOME` | Account `Internet - SIL` |
| Message contains `Okoa` | Ignore |

### Transfers between your own accounts

Sending M-PESA to your KCB account produces two messages: M-PESA "sent to KCB ... for account ..." and
KCB "credited ... from MPESA". Same amount, opposite directions, within the match window (settings), and
either a shared reference or each side naming the other → recorded **once** as a Contra Entry between the
two ledger accounts. The second message is marked **Linked** (its own charges are still posted). If the
first side was already posted as income / expense, it is cancelled and replaced automatically (switch off
in settings).

### Duplicates

- Every message is fingerprinted (sender + text, ignoring the phone timestamp). Re-sending the same SMS
  does nothing.
- A transaction code / bank reference already posted for the same source marks the new message
  **Ignored – Duplicate**.

### Statuses

`Pending` → `Posted` / `Linked`, or `Parsed` (auto-post off), `Ignored` (not a transaction, duplicate or
rule), `Unparsed` (has an amount but the wording wasn't understood — add a pattern), `Failed` (see the
error; fix and click **Process**). To override one message, tick *Use My Party and Account*, set them,
save and **Re-process**. Re-processing cancels the entries made earlier.

An hourly job picks up anything still `Pending`.

## Phone app

Download the latest `sms-ledger-<version>.apk` from this repository's **Releases** page on the phone and
install it (allow installs from your browser when Android asks). Every push to `main` that changes
`android/` builds a new one; it installs over the old version. Setup steps are in `android/README.md`.
Android only — iOS does not let apps read SMS.

## Tests

```bash
# the parsers (no Frappe needed)
cd apps/sms_ledger && python -m unittest sms_ledger.tests.test_parsers -v

# SMS in through the phone API, entries out, on a site with ERPNext
bench --site <site> run-tests --app sms_ledger --module sms_ledger.tests.test_posting
```

## Note on KCB wording

Safaricom's M-PESA formats are well documented. KCB does not publish its SMS templates, so the KCB
source uses a keyword-based parser (credited / debited, KES amount, Ref, Bal, A/C ****1234) rather than
one fixed template. Paste a few of your real KCB alerts into **Test Message**; if a field comes out wrong,
add a Custom Pattern for that wording.
