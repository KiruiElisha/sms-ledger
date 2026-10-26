package com.smsledger.app

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

data class SmsData(val id: String, val sender: String, val body: String, val timestamp: Long) {
    /** Same message read twice (live receiver + inbox scan) collapses to one. */
    val dedupeKey: String
        get() = SenderRule.normalize(sender) + "|" + body.trim().replace(Regex("\\s+"), " ")

    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("sender", sender)
        .put("body", body)
        .put("timestamp", timestamp)
}

class ErpClient(private val prefs: Prefs) {

    fun getConfig(): JSONObject = request("GET", "sms_ledger.api.get_config", null)

    fun ingest(deviceId: String, messages: List<SmsData>): JSONObject {
        val arr = JSONArray()
        messages.forEach { arr.put(it.toJson()) }
        val payload = JSONObject().put("device_id", deviceId).put("messages", arr)
        return request("POST", "sms_ledger.api.ingest", payload)
    }

    private fun request(method: String, apiMethod: String, body: JSONObject?): JSONObject {
        val url = URL("${prefs.baseUrl}/api/method/$apiMethod")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 20_000
            readTimeout = 60_000
            setRequestProperty("Authorization", "token ${prefs.apiKey}:${prefs.apiSecret}")
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (body != null) {
                conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            if (code !in 200..299) {
                throw IOException("HTTP $code: ${serverError(text)}")
            }
            val json = JSONObject(text)
            return json.optJSONObject("message") ?: JSONObject()
        } finally {
            conn.disconnect()
        }
    }

    private fun serverError(text: String): String = try {
        val j = JSONObject(text)
        val msgs = j.optString("_server_messages")
        when {
            msgs.isNotEmpty() -> JSONObject(JSONArray(msgs).getString(0)).optString("message")
            j.has("exception") -> j.optString("exception")
            else -> text.take(200)
        }
    } catch (e: Exception) {
        text.take(200)
    }
}
