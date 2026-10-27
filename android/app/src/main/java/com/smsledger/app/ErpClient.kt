package com.smsledger.app

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

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

    fun getConfig(): JSONObject = call("GET", "sms_ledger.api.get_config") as? JSONObject ?: JSONObject()

    fun ingest(deviceId: String, messages: List<SmsData>): JSONObject {
        val arr = JSONArray()
        messages.forEach { arr.put(it.toJson()) }
        val payload = JSONObject().put("device_id", deviceId).put("messages", arr)
        return call("POST", "sms_ledger.api.ingest", payload) as? JSONObject ?: JSONObject()
    }

    fun dashboard(month: String): JSONObject =
        call("GET", "sms_ledger.phone.dashboard", JSONObject().put("month", month)) as? JSONObject ?: JSONObject()

    fun activity(start: Int, status: String?): JSONArray {
        val args = JSONObject().put("start", start).put("page_length", PAGE)
        if (status != null) args.put("status", status)
        return call("GET", "sms_ledger.phone.activity", args) as? JSONArray ?: JSONArray()
    }

    fun accounts(): JSONArray = call("GET", "sms_ledger.phone.accounts") as? JSONArray ?: JSONArray()

    fun retry(name: String): JSONObject =
        call("POST", "sms_ledger.phone.retry", JSONObject().put("name", name)) as? JSONObject ?: JSONObject()

    fun recategorise(name: String, account: String, remember: Boolean): JSONObject {
        val args = JSONObject().put("name", name).put("account", account).put("remember", if (remember) 1 else 0)
        return call("POST", "sms_ledger.phone.recategorise", args) as? JSONObject ?: JSONObject()
    }

    /** The method's "message": a JSON object or array. GET sends args as the query string. */
    private fun call(method: String, apiMethod: String, args: JSONObject? = null): Any? {
        val query = if (method == "GET" && args != null) "?" + queryString(args) else ""
        val url = URL("${prefs.baseUrl}/api/method/$apiMethod$query")
        val body = if (method == "GET") null else args
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
            return JSONObject(text).opt("message")
        } finally {
            conn.disconnect()
        }
    }

    private fun queryString(args: JSONObject): String =
        args.keys().asSequence().joinToString("&") { key ->
            URLEncoder.encode(key, "UTF-8") + "=" + URLEncoder.encode(args.get(key).toString(), "UTF-8")
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

    companion object {
        const val PAGE = 30
    }
}
