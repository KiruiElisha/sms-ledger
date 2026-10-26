# SMS Ledger – Android app

Reads SMS from the senders configured under **SMS Source** in ERPNext and uploads them to
`sms_ledger.api.ingest`. Nothing else in your inbox is read or sent.

- **Live:** a receiver catches new messages as they arrive and uploads them straight away (queued
  on the phone if offline).
- **Catch-up:** every 15 minutes (and on *Sync now*) it re-reads the inbox since the last scan, so
  messages that arrived while the phone was off or the app was stopped are not missed. The first sync
  goes back the number of days set in *SMS Ledger Settings* (default 30).
- The sender list is refreshed from ERPNext on every sync, so adding a bank in ERPNext needs no app update.

## Get the app

GitHub Actions builds it on every push to `main` that touches this folder
(`.github/workflows/android.yml`) and publishes the APK on the repository's **Releases** page. Open
that page on the phone, download the APK and install it.

To build it yourself: open this folder in Android Studio, or run `./gradlew assembleRelease`.

**Signing.** Builds are signed with `app/sideload.keystore` (password `android`), so each new APK
installs over the last one. Before giving the app to anyone else, use your own key: add the repository
secrets `SMS_LEDGER_KEYSTORE_BASE64` (the keystore, base64), `SMS_LEDGER_KEYSTORE_PASSWORD`,
`SMS_LEDGER_KEY_ALIAS` and `SMS_LEDGER_KEY_PASSWORD`. Changing the key means uninstalling the old
app once.

The app uses SMS permissions, which Google Play only allows for default SMS apps, so install it
directly (side-load) rather than through Play.

## Use

1. Enter the ERPNext address (`https://...`), API key and secret of the device user.
2. *Save and test connection* → it shows which senders it is watching.
3. *Allow SMS access*.
4. On phones with aggressive battery saving (Tecno, Infinix, Xiaomi, Samsung), set the app's battery
   usage to *Unrestricted* so background syncs keep running.
