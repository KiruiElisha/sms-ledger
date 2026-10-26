package com.smsledger.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/** Catches new SMS as they arrive, keeps the ones from configured senders and triggers a sync. */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val prefs = Prefs(context)
        val rules = prefs.senders
        if (rules.isEmpty() || !prefs.isConfigured) return

        val queue = PendingQueue(context)
        var queued = 0
        // a long message arrives in several parts from the same sender
        parts.groupBy { it.originatingAddress ?: "" }.forEach { (address, msgParts) ->
            if (address.isEmpty() || rules.none { it.matches(address) }) return@forEach
            val body = msgParts.joinToString("") { it.messageBody ?: "" }
            val ts = msgParts.first().timestampMillis
            queue.add(SmsData("rx-$address-$ts", address, body, ts))
            queued++
        }
        if (queued > 0) SyncWorker.runNow(context)
    }
}
