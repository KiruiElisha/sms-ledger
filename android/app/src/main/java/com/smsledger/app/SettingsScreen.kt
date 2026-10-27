package com.smsledger.app

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.materialswitch.MaterialSwitch

/** The ERPNext connection, SMS access, and the app's own preferences. */
class SettingsScreen(
    parent: ViewGroup,
    private val prefs: Prefs,
    private val hasSmsPermission: () -> Boolean,
    private val askPermission: () -> Unit,
    private val changed: () -> Unit,  // the other tabs reload next time they are shown
) {
    val view: View = LayoutInflater.from(parent.context).inflate(R.layout.screen_settings, parent, false)
    private val ctx = parent.context
    private val url = view.findViewById<TextView>(R.id.url)
    private val apiKey = view.findViewById<TextView>(R.id.api_key)
    private val apiSecret = view.findViewById<TextView>(R.id.api_secret)
    private val status = view.findViewById<TextView>(R.id.status)

    init {
        url.text = prefs.baseUrl
        apiKey.text = prefs.apiKey
        apiSecret.text = prefs.apiSecret
        view.findViewById<View>(R.id.save).setOnClickListener { saveAndTest() }
        view.findViewById<View>(R.id.permission).setOnClickListener { askPermission() }
        view.findViewById<View>(R.id.sync).setOnClickListener { syncNow() }
        view.findViewById<View>(R.id.history).setOnClickListener { readOlder() }
        view.findViewById<View>(R.id.find_senders).setOnClickListener { findSenders() }
        view.findViewById<MaterialSwitch>(R.id.notify).apply {
            isChecked = prefs.notify
            setOnCheckedChangeListener { _, on -> prefs.notify = on }
        }
        view.findViewById<MaterialSwitch>(R.id.hide_amounts).apply {
            isChecked = prefs.hideAmounts
            setOnCheckedChangeListener { _, on -> prefs.hideAmounts = on; changed() }
        }
    }

    fun refresh() {
        status.text = statusText()
    }

    private fun syncNow() {
        if (!prefs.isConfigured) return toast("Save the connection details first")
        SyncWorker.runNow(ctx)
        toast("Sync started")
        status.postDelayed({ refresh() }, 4000)
    }

    private fun readOlder() {
        if (!prefs.isConfigured || prefs.senders.isEmpty()) return toast("Connect to ERPNext first")
        if (!hasSmsPermission()) return askPermission()
        val day = 24L * 60 * 60 * 1000
        val choices = listOf("Last 3 months" to 92 * day, "Last year" to 366 * day, "Everything" to Long.MAX_VALUE)
        MaterialAlertDialogBuilder(ctx)
            .setTitle(R.string.read_older)
            .setItems(choices.map { it.first }.toTypedArray()) { _, i ->
                val back = choices[i].second
                prefs.rewindScan(if (back == Long.MAX_VALUE) 1L else System.currentTimeMillis() - back)
                SyncWorker.runNow(ctx)
                toast("Reading ${choices[i].first.lowercase()}; this can take a few minutes")
                status.postDelayed({ refresh() }, 6000)
            }
            .show()
    }

    /** Which inbox senders send Ksh/KES, so a source can be pointed at the right sender name. */
    private fun findSenders() {
        if (!hasSmsPermission()) return askPermission()
        toast("Looking through the inbox…")
        Background.run({ SenderFinder.find(ctx, prefs.senders) }) { result ->
            val found = result.getOrElse { return@run toast(it.message ?: "Could not read the inbox") }
            val lines = found.take(15).joinToString("\n") { s ->
                "${if (s.watched) "✓" else "✗"} ${s.address}: ${s.count} message${if (s.count == 1) "" else "s"}"
            }
            MaterialAlertDialogBuilder(ctx)
                .setTitle(R.string.find_senders)
                .setMessage(
                    if (found.isEmpty()) "No message on this phone mentions Ksh or KES."
                    else "$lines\n\n✓ is read by an SMS Source. For a ✗ sender you want, add its name as a " +
                        "Sender ID on that SMS Source in ERPNext, then Sync now."
                )
                .setPositiveButton(android.R.string.ok, null)
                .show()
        }
    }

    private fun saveAndTest() {
        val u = url.text.toString().trim()
        if (!u.startsWith("https://")) return toast("Use the https:// address of your ERPNext site")
        prefs.baseUrl = u
        prefs.apiKey = apiKey.text.toString()
        prefs.apiSecret = apiSecret.text.toString()
        status.text = "Testing connection…"
        Background.run({ ErpClient(prefs).getConfig() }) { result ->
            val message = result.fold(
                onSuccess = { cfg ->
                    prefs.applyConfig(cfg)
                    SyncWorker.schedule(ctx)
                    SyncWorker.runNow(ctx)
                    changed()
                    val senders = prefs.senders.joinToString { it.senderId }
                    "Connected as ${cfg.optString("user")}.\nWatching senders: " +
                        "${senders.ifEmpty { "none - enable an SMS Source in ERPNext" }}\n" +
                        "First sync reads the last ${prefs.syncDaysBack} days."
                },
                onFailure = { "Connection failed: ${it.message ?: it.javaClass.simpleName}" },
            )
            status.text = message + "\n\n" + statusText()
        }
    }

    private fun statusText(): String {
        val senders = prefs.senders.joinToString { it.senderId }.ifEmpty { "-" }
        return buildString {
            appendLine("SMS access: ${if (hasSmsPermission()) "allowed" else "NOT allowed"}")
            appendLine("Senders: $senders")
            appendLine("Waiting to upload: ${PendingQueue(ctx).size()}")
            append("Last sync: ${prefs.lastSyncSummary}")
        }
    }

    private fun toast(message: String) = Toast.makeText(ctx, message, Toast.LENGTH_SHORT).show()
}
