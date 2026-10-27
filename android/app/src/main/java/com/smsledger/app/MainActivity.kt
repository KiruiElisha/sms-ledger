package com.smsledger.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.bottomnavigation.BottomNavigationView

/** Three tabs: Home (the month), Activity (every message) and Settings (the connection). */
class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var nav: BottomNavigationView
    private lateinit var home: HomeScreen
    private lateinit var feed: ActivityScreen
    private lateinit var settings: SettingsScreen
    private val loaded = mutableSetOf<Int>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)
        val screens = findViewById<FrameLayout>(R.id.screens)
        home = HomeScreen(screens, prefs) { nav.selectedItemId = R.id.tab_activity; feed.showAttention() }
        feed = ActivityScreen(screens, this, prefs)
        settings = SettingsScreen(screens, prefs, ::hasSmsPermission, ::askPermissions) { loaded.clear() }
        listOf(home.view, feed.view, settings.view).forEach { screens.addView(it) }

        nav = findViewById(R.id.nav)
        nav.setOnItemSelectedListener { show(it.itemId); true }
        val first = intent.getIntExtra(EXTRA_TAB, if (prefs.isConfigured) R.id.tab_home else R.id.tab_settings)
        nav.selectedItemId = first
        show(first)

        if (prefs.isConfigured) SyncWorker.schedule(this)
        if (!hasSmsPermission() || needsNotificationPermission()) askPermissions()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getIntExtra(EXTRA_TAB, 0).takeIf { it != 0 }?.let {
            nav.selectedItemId = it
            loaded.remove(it)
            show(it)
        }
    }

    override fun onResume() {
        super.onResume()
        settings.refresh()
    }

    /** Each tab loads the first time it is opened, and again by pulling down. */
    private fun show(tab: Int) {
        home.view.visibility = if (tab == R.id.tab_home) View.VISIBLE else View.GONE
        feed.view.visibility = if (tab == R.id.tab_activity) View.VISIBLE else View.GONE
        settings.view.visibility = if (tab == R.id.tab_settings) View.VISIBLE else View.GONE
        if (!loaded.add(tab)) return
        when (tab) {
            R.id.tab_home -> home.load()
            R.id.tab_activity -> feed.reload()
            R.id.tab_settings -> settings.refresh()
        }
    }

    private fun hasSmsPermission(): Boolean =
        checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED

    private fun needsNotificationPermission() = Build.VERSION.SDK_INT >= 33 &&
        checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED

    private fun askPermissions() {
        val wanted = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS)
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        requestPermissions(wanted.toTypedArray(), REQ_PERMISSIONS)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_PERMISSIONS) return
        settings.refresh()
        if (hasSmsPermission() && prefs.isConfigured) SyncWorker.runNow(this)
    }

    companion object {
        const val EXTRA_TAB = "tab"
        private const val REQ_PERMISSIONS = 42
    }
}
