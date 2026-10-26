package com.smsledger.app

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var url: EditText
    private lateinit var apiKey: EditText
    private lateinit var apiSecret: EditText
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        url = findViewById(R.id.url)
        apiKey = findViewById(R.id.api_key)
        apiSecret = findViewById(R.id.api_secret)
        status = findViewById(R.id.status)

        url.setText(prefs.baseUrl)
        apiKey.setText(prefs.apiKey)
        apiSecret.setText(prefs.apiSecret)

        findViewById<Button>(R.id.save).setOnClickListener { saveAndTest() }
        findViewById<Button>(R.id.permission).setOnClickListener { askPermission() }
        findViewById<Button>(R.id.sync).setOnClickListener {
            if (!prefs.isConfigured) {
                toast("Save the connection details first")
            } else {
                SyncWorker.runNow(this)
                toast("Sync started")
                status.postDelayed({ refreshStatus() }, 4000)
            }
        }

        if (prefs.isConfigured) SyncWorker.schedule(this)
        if (!hasSmsPermission()) askPermission()
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
    }

    private fun saveAndTest() {
        val u = url.text.toString().trim()
        if (!u.startsWith("https://")) {
            toast("Use the https:// address of your ERPNext site")
            return
        }
        prefs.baseUrl = u
        prefs.apiKey = apiKey.text.toString()
        prefs.apiSecret = apiSecret.text.toString()
        status.text = "Testing connection..."

        Thread {
            val message = try {
                val cfg = ErpClient(prefs).getConfig()
                prefs.applyConfig(cfg)
                SyncWorker.schedule(this)
                SyncWorker.runNow(this)
                val senders = prefs.senders.joinToString { it.senderId }
                "Connected as ${cfg.optString("user")}.\nWatching senders: ${senders.ifEmpty { "none - enable an SMS Source in ERPNext" }}\nFirst sync reads the last ${prefs.syncDaysBack} days."
            } catch (e: Exception) {
                "Connection failed: ${e.message ?: e.javaClass.simpleName}"
            }
            runOnUiThread { status.text = message + "\n\n" + statusText() }
        }.start()
    }

    private fun refreshStatus() {
        status.text = statusText()
    }

    private fun statusText(): String {
        val senders = prefs.senders.joinToString { it.senderId }.ifEmpty { "-" }
        return buildString {
            appendLine("SMS access: ${if (hasSmsPermission()) "allowed" else "NOT allowed"}")
            appendLine("Senders: $senders")
            appendLine("Waiting to upload: ${PendingQueue(this@MainActivity).size()}")
            append("Last sync: ${prefs.lastSyncSummary}")
        }
    }

    private fun hasSmsPermission(): Boolean =
        checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED

    private fun askPermission() {
        requestPermissions(arrayOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS), REQ_SMS)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_SMS) {
            refreshStatus()
            if (hasSmsPermission() && prefs.isConfigured) SyncWorker.runNow(this)
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    companion object {
        private const val REQ_SMS = 42
    }
}
