package com.smsledger.app

import android.annotation.SuppressLint
import android.content.Context
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject

/** One "Sender ID" row from an SMS Source in ERPNext. */
data class SenderRule(val senderId: String, val matchType: String) {
    fun matches(address: String?): Boolean {
        val a = normalize(address ?: return false)
        val s = normalize(senderId)
        if (s.isEmpty()) return false
        return when (matchType) {
            "Starts With" -> a.startsWith(s)
            "Contains" -> a.contains(s)
            else -> a == s
        }
    }

    companion object {
        fun normalize(v: String) = v.uppercase().filter { it.isLetterOrDigit() }
    }
}

class Prefs(private val ctx: Context) {
    private val sp = ctx.getSharedPreferences("sms_ledger", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = sp.getString("base_url", "") ?: ""
        set(v) = sp.edit().putString("base_url", v.trim().trimEnd('/')).apply()

    var apiKey: String
        get() = sp.getString("api_key", "") ?: ""
        set(v) = sp.edit().putString("api_key", v.trim()).apply()

    var apiSecret: String
        get() = sp.getString("api_secret", "") ?: ""
        set(v) = sp.edit().putString("api_secret", v.trim()).apply()

    /** Inbox messages newer than this (epoch ms) are read on the next sync. 0 = never synced. */
    var lastScanMs: Long
        get() = sp.getLong("last_scan_ms", 0L)
        set(v) = sp.edit().putLong("last_scan_ms", v).apply()

    var syncDaysBack: Int
        get() = sp.getInt("sync_days_back", 30)
        set(v) = sp.edit().putInt("sync_days_back", v).apply()

    var serverEnabled: Boolean
        get() = sp.getBoolean("server_enabled", true)
        set(v) = sp.edit().putBoolean("server_enabled", v).apply()

    var lastSyncSummary: String
        get() = sp.getString("last_sync_summary", "Never synced") ?: ""
        set(v) = sp.edit().putString("last_sync_summary", v).apply()

    var senders: List<SenderRule>
        get() {
            val raw = sp.getString("senders", "[]") ?: "[]"
            val arr = JSONArray(raw)
            return (0 until arr.length()).map {
                val o = arr.getJSONObject(it)
                SenderRule(o.optString("sender_id"), o.optString("match_type", "Exact"))
            }
        }
        set(v) {
            val arr = JSONArray()
            v.forEach { arr.put(JSONObject().put("sender_id", it.senderId).put("match_type", it.matchType)) }
            sp.edit().putString("senders", arr.toString()).apply()
        }

    val isConfigured: Boolean
        get() = baseUrl.startsWith("https://") && apiKey.isNotBlank() && apiSecret.isNotBlank()

    @get:SuppressLint("HardwareIds")
    val deviceId: String
        get() = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"

    /** Store the sender list and options returned by sms_ledger.api.get_config. */
    fun applyConfig(cfg: JSONObject) {
        serverEnabled = cfg.optInt("enabled", 1) == 1
        syncDaysBack = cfg.optInt("sync_days_back", 30)
        val rules = mutableListOf<SenderRule>()
        val sources = cfg.optJSONArray("sources") ?: JSONArray()
        for (i in 0 until sources.length()) {
            val senders = sources.getJSONObject(i).optJSONArray("senders") ?: continue
            for (j in 0 until senders.length()) {
                val s = senders.getJSONObject(j)
                rules.add(SenderRule(s.optString("sender_id"), s.optString("match_type", "Exact")))
            }
        }
        senders = rules
    }
}
