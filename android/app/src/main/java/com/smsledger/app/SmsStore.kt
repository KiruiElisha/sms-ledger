package com.smsledger.app

import android.content.Context
import android.provider.Telephony
import org.json.JSONArray
import java.io.File

/** Reads matching messages from the phone's SMS inbox. */
object InboxReader {
    private const val COL_ID = "_id"
    private const val COL_ADDRESS = "address"
    private const val COL_BODY = "body"
    private const val COL_DATE = "date"

    fun read(ctx: Context, sinceMs: Long, rules: List<SenderRule>): List<SmsData> {
        if (rules.isEmpty()) return emptyList()
        val out = mutableListOf<SmsData>()
        // public, stable column names of the SMS content provider
        val projection = arrayOf(COL_ID, COL_ADDRESS, COL_BODY, COL_DATE)
        ctx.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            projection,
            "$COL_DATE > ?",
            arrayOf(sinceMs.toString()),
            "$COL_DATE ASC"
        )?.use { c ->
            val iId = c.getColumnIndexOrThrow(COL_ID)
            val iAddr = c.getColumnIndexOrThrow(COL_ADDRESS)
            val iBody = c.getColumnIndexOrThrow(COL_BODY)
            val iDate = c.getColumnIndexOrThrow(COL_DATE)
            while (c.moveToNext()) {
                val addr = c.getString(iAddr) ?: continue
                if (rules.none { it.matches(addr) }) continue
                val body = c.getString(iBody) ?: continue
                out.add(SmsData("inbox-" + c.getLong(iId), addr, body, c.getLong(iDate)))
            }
        }
        return out
    }
}

/** A sender in the inbox that sends money messages: how many, and whether a source watches it. */
data class MoneySender(val address: String, val count: Int, val watched: Boolean)

object SenderFinder {
    private val money = Regex("(?:Ksh|KES)\\s?[\\d,]+", RegexOption.IGNORE_CASE)

    /** Every sender whose messages mention Ksh/KES, most messages first. Nothing leaves the phone. */
    fun find(ctx: Context, rules: List<SenderRule>): List<MoneySender> {
        val counts = mutableMapOf<String, Int>()
        ctx.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI, arrayOf("address", "body"), null, null, null
        )?.use { c ->
            val iAddr = c.getColumnIndexOrThrow("address")
            val iBody = c.getColumnIndexOrThrow("body")
            while (c.moveToNext()) {
                val addr = c.getString(iAddr) ?: continue
                if (money.containsMatchIn(c.getString(iBody) ?: "")) counts[addr] = (counts[addr] ?: 0) + 1
            }
        }
        return counts.entries.sortedByDescending { it.value }
            .map { (addr, n) -> MoneySender(addr, n, rules.any { it.matches(addr) }) }
    }
}

/** Messages caught by the live receiver, kept until the server has them. */
class PendingQueue(ctx: Context) {
    private val file = File(ctx.filesDir, "pending_sms.json")

    fun add(msg: SmsData) = synchronized(LOCK) {
        val arr = load()
        arr.put(msg.toJson())
        // keep the queue bounded if the server is unreachable for a long time
        val trimmed = if (arr.length() > 2000) {
            JSONArray().also { n -> for (i in arr.length() - 2000 until arr.length()) n.put(arr.get(i)) }
        } else arr
        file.writeText(trimmed.toString())
    }

    fun readAll(): List<SmsData> = synchronized(LOCK) {
        val arr = load()
        (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            SmsData(o.getString("id"), o.getString("sender"), o.getString("body"), o.getLong("timestamp"))
        }
    }

    fun remove(ids: Collection<String>) = synchronized(LOCK) {
        if (ids.isEmpty()) return@synchronized
        val keep = JSONArray()
        val arr = load()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            if (o.getString("id") !in ids) keep.put(o)
        }
        file.writeText(keep.toString())
    }

    fun size(): Int = synchronized(LOCK) { load().length() }

    private fun load(): JSONArray = try {
        if (file.exists()) JSONArray(file.readText()) else JSONArray()
    } catch (e: Exception) {
        JSONArray()
    }

    companion object {
        private val LOCK = Any()
    }
}
