package com.smsledger.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/** "3 messages sent to ERPNext", with the first lines of each, after a sync. */
object Notifier {
    private const val CHANNEL = "recorded"
    private const val ID = 1
    private val amount = Regex("(?:Ksh|KES)\\s?[\\d,]+(?:\\.\\d{1,2})?", RegexOption.IGNORE_CASE)

    fun recorded(ctx: Context, messages: List<SmsData>) {
        if (messages.isEmpty() || !Prefs(ctx).notify || !allowed(ctx)) return
        ensureChannel(ctx)
        val lines = messages.takeLast(5).map { line(it) }
        val title = "${messages.size} message${if (messages.size == 1) "" else "s"} sent to ERPNext"
        val open = PendingIntent.getActivity(
            ctx, 0,
            Intent(ctx, MainActivity::class.java).putExtra(MainActivity.EXTRA_TAB, R.id.tab_activity),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val style = NotificationCompat.InboxStyle().setBigContentTitle(title)
        lines.forEach { style.addLine(it) }
        val notification = NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_notify)
            .setColor(ContextCompat.getColor(ctx, R.color.brand))
            .setContentTitle(title)
            .setContentText(lines.last())
            .setStyle(style)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(ctx).notify(ID, notification)
    }

    /** "MPESA: Ksh30.00 · sent to LAMECK OKEMWA" rather than the whole SMS. */
    private fun line(sms: SmsData): String {
        val money = amount.find(sms.body)?.value ?: ""
        val rest = if (money.isEmpty()) sms.body else sms.body.substringAfter(money).trim(' ', '.')
        return "${sms.sender}: $money ${rest.take(40)}".trim()
    }

    private fun allowed(ctx: Context) = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun ensureChannel(ctx: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = ctx.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, ctx.getString(R.string.channel_name), NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
    }
}
