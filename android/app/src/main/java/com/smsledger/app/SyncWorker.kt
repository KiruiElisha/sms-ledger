package com.smsledger.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * 1. refreshes the sender list from ERPNext
 * 2. collects messages caught live + anything in the inbox since the last scan
 * 3. uploads them in batches; the server ignores duplicates
 */
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val ctx = applicationContext
        val prefs = Prefs(ctx)
        if (!prefs.isConfigured) return@withContext Result.success()

        try {
            val client = ErpClient(prefs)
            prefs.applyConfig(client.getConfig())
            if (!prefs.serverEnabled) {
                prefs.lastSyncSummary = "${stamp()} - paused (SMS Ledger is disabled in ERPNext)"
                return@withContext Result.success()
            }

            val queue = PendingQueue(ctx)
            val queued = queue.readAll()
            val startedAt = System.currentTimeMillis()
            val since = if (prefs.lastScanMs == 0L) {
                startedAt - prefs.syncDaysBack * DAY_MS
            } else {
                prefs.lastScanMs - OVERLAP_MS   // re-read a little; the server drops duplicates
            }

            val canRead = ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_SMS) ==
                PackageManager.PERMISSION_GRANTED
            val inbox = if (canRead) InboxReader.read(ctx, since, prefs.senders) else emptyList()

            val all = (queued + inbox).distinctBy { it.dedupeKey }.sortedBy { it.timestamp }
            var accepted = 0
            var duplicates = 0
            all.chunked(BATCH).forEach { batch ->
                val res = client.ingest(prefs.deviceId, batch)
                accepted += res.optInt("accepted")
                duplicates += res.optInt("duplicates")
            }

            queue.remove(queued.map { it.id })
            if (canRead) prefs.lastScanMs = startedAt
            prefs.lastSyncSummary = "${stamp()} - sent ${all.size}: $accepted new, $duplicates already in ERPNext" +
                if (!canRead) " (SMS permission missing: only live messages)" else ""
            Result.success()
        } catch (e: Exception) {
            prefs.lastSyncSummary = "${stamp()} - failed: ${e.message ?: e.javaClass.simpleName}"
            if (runAttemptCount < 5) Result.retry() else Result.failure()
        }
    }

    private fun stamp(): String = SimpleDateFormat("dd MMM HH:mm", Locale.getDefault()).format(Date())

    companion object {
        private const val DAY_MS = 24L * 60 * 60 * 1000
        private const val OVERLAP_MS = 6L * 60 * 60 * 1000
        private const val BATCH = 100
        private const val PERIODIC = "sms_ledger_periodic"
        private const val NOW = "sms_ledger_now"

        private val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        /** Every 15 minutes (Android's minimum), as a safety net for anything the receiver missed. */
        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(network)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun runNow(ctx: Context) {
            val req = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(network)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(ctx).enqueueUniqueWork(NOW, ExistingWorkPolicy.APPEND_OR_REPLACE, req)
        }
    }
}
