package com.smsledger.app

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
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
