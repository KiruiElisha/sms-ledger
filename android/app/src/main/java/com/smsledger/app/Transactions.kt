package com.smsledger.app

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale

/** How an SMS Transaction from sms_ledger.phone reads on screen. */
object Transactions {
    private val serverTime = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
    private val shown = SimpleDateFormat("d MMM, HH:mm", Locale.getDefault())
    private val palette = intArrayOf(0xFF0B7A47.toInt(), 0xFF1565C0.toInt(), 0xFF6A1B9A.toInt(),
        0xFFAD1457.toInt(), 0xFFEF6C00.toInt(), 0xFF00838F.toInt(), 0xFF4E342E.toInt())

    fun isIn(t: JSONObject) = t.optString("direction") == "In"
    fun amount(t: JSONObject) = t.optDouble("amount", 0.0).takeUnless { it.isNaN() } ?: 0.0

    fun title(t: JSONObject): String =
        t.optString("counterparty").takeIf { it.isNotBlank() && it != "null" }
            ?: t.optString("transaction_type").takeIf { it.isNotBlank() && it != "null" }
            ?: t.optString("source")

    fun subtitle(t: JSONObject): String {
        val date = t.optString("transaction_date").takeIf { it.isNotBlank() && it != "null" }
            ?.let { runCatching { shown.format(serverTime.parse(it.take(19))!!) }.getOrNull() }
        val kind = t.optString("transaction_type").takeIf { it.isNotBlank() && it != "null" }
        return listOfNotNull(t.optString("source"), kind, date).joinToString(" · ")
    }

    fun signedAmount(t: JSONObject): String {
        if (amount(t) == 0.0) return ""
        return (if (isIn(t)) "+ " else "− ") + Money.format(amount(t))
    }

    fun amountColor(t: JSONObject) = if (isIn(t)) R.color.money_in else R.color.money_out

    fun statusColor(t: JSONObject) = when (t.optString("status")) {
        "Posted", "Linked" -> R.color.money_in
        "Failed", "Unparsed" -> R.color.money_out
        "Pending", "Parsed" -> R.color.status_warn
        else -> R.color.muted
    }

    fun needsAttention(t: JSONObject) = t.optString("status") in setOf("Failed", "Unparsed")

    /** The same payee always gets the same colour. */
    fun avatarColor(title: String): Int = palette[Math.floorMod(title.lowercase().hashCode(), palette.size)]

    fun details(t: JSONObject): String = buildString {
        appendLine(subtitle(t))
        t.optString("reference").takeIf { it.isNotBlank() && it != "null" }?.let { appendLine("Ref $it") }
        val charges = t.optDouble("charges", 0.0)
        if (charges > 0) appendLine("Charges ${Money.format(charges)}")
        t.optString("offset_account").takeIf { it.isNotBlank() && it != "null" }?.let {
            appendLine((if (t.optInt("is_transfer") == 1) "Transfer with " else "Account: ") + it)
        }
        append("Status: ${t.optString("status")}")
    }
}
