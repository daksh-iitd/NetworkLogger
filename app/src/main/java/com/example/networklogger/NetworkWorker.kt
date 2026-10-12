// NetworkWorker.kt

package com.example.networklogger

import android.app.ActivityManager
import android.content.Context
import android.os.Environment
import android.os.StatFs
import android.util.Log
import androidx.work.WorkerParameters
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.telephony.TelephonyManager
import android.content.ContentValues
import android.content.ContentUris
import android.net.Uri
import android.provider.MediaStore
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.core.app.NotificationCompat
import android.content.pm.ServiceInfo
import androidx.appcompat.app.AppCompatActivity


class NetworkWorker(
    context: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(context, workerParams) {

    companion object {
        // Generous margin above the worst-case Doze-induced gap we've observed in
        // real logs (a few hundred seconds) so a throttled-but-alive session never
        // trips this — only a genuinely dead LoggingService should.
        private const val WATCHDOG_THRESHOLD_MS = 10 * 60 * 1000L
        private const val WATCHDOG_NOTIFICATION_ID = 3001
    }

    private var batteryPercent = 0

    // NEW
    private var totalRamGB = 0f
    private var usedRamGB = 0f
    private var availableRamGB = 0f

    private var totalStorageGB = 0f
    private var usedStorageGB = 0f
    private var freeStorageGB = 0f

    private var networkType = "Unknown"
    private var operatorName = "Unknown"
    private var signalLevel = "Unknown"
    private var cellId = "N/A"
    private var tac = "N/A"

    override suspend fun doWork(): Result {
        Log.d("NetworkWorker", "Background work running")

        // This keeps the Worker alive on real devices
        // Wrap setForeground in try-catch — don't let it kill the whole worker
        // On rooted phones, foreground service can be blocked by SELinux/Magisk
        // We try it but never let it crash the app
        try {
            setForeground(createForegroundInfo())
            Log.d("NetworkWorker", "Foreground service started")
        } catch (t: Throwable) {
            Log.w("NetworkWorker", "Foreground service blocked: ${t.message}")
            // Safe to continue — worker logs data without foreground service
        }

        return try {
            logBatteryInfo()
            logStorageInfo()
            logRamInfo()
            logTelecomInfo()
            saveBackgroundLog()
            checkLoggingWatchdog()
            Log.d("NetworkWorker", "Completed successfully")
            Result.success()
        } catch (e: Exception) {
            Log.e("NetworkWorker", "doWork() failed: ${e.message}", e)
            Result.failure()
        }
    }

    // NetworkWorker runs on its own independent WorkManager schedule, so it can
    // still fire even if LoggingService's process was killed by the OS. If a
    // session claims to be active but hasn't ticked in a long time, that means
    // the service died silently (not via the Stop button) — alert the user.
    private fun checkLoggingWatchdog() {
        val prefs = applicationContext.getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
        val sessionActive = prefs.getBoolean(MainActivity.KEY_SESSION_ACTIVE, false)
        if (!sessionActive) return

        val lastTick = prefs.getLong(MainActivity.KEY_LAST_TICK_MS, 0L)
        if (lastTick == 0L) return

        val staleMs = System.currentTimeMillis() - lastTick
        if (staleMs < WATCHDOG_THRESHOLD_MS) return

        Log.w("NetworkWorker", "Logging watchdog: no tick in ${staleMs / 1000}s — session appears to have died")

        // Stop reporting an active session so this doesn't re-fire every 15 minutes.
        prefs.edit().putBoolean(MainActivity.KEY_SESSION_ACTIVE, false).apply()

        // Let MainActivity know too, in case it's open and showing a stale "logging" state.
        val statusIntent = Intent(LoggingService.ACTION_STATUS_CHANGED).apply {
            setPackage(applicationContext.packageName)
            putExtra(LoggingService.EXTRA_IS_RUNNING, false)
        }
        applicationContext.sendBroadcast(statusIntent)

        postWatchdogNotification()
    }

    private fun postWatchdogNotification() {
        val channelId = "network_logger_watchdog_channel"
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            val channel = android.app.NotificationChannel(
                channelId, "Logging Alerts", android.app.NotificationManager.IMPORTANCE_HIGH
            )
            applicationContext.getSystemService(android.app.NotificationManager::class.java)
                .createNotificationChannel(channel)
        }

        val openAppIntent = applicationContext.packageManager.getLaunchIntentForPackage(applicationContext.packageName)
        val contentPendingIntent = android.app.PendingIntent.getActivity(
            applicationContext, 0, openAppIntent,
            android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(applicationContext, channelId)
            .setContentTitle("NetworkLogger stopped unexpectedly")
            .setContentText("Logging isn't active anymore. Tap to reopen and restart it.")
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(contentPendingIntent)
            .build()

        applicationContext.getSystemService(android.app.NotificationManager::class.java)
            .notify(WATCHDOG_NOTIFICATION_ID, notification)
    }


    private fun createForegroundInfo(): ForegroundInfo {
        val channelId = "network_logger_channel"
        val channelName = "Network Logger"

        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            val channel = android.app.NotificationChannel(
                channelId,
                channelName,
                android.app.NotificationManager.IMPORTANCE_LOW
            )
            val manager = applicationContext.getSystemService(
                android.app.NotificationManager::class.java
            )
            manager.createNotificationChannel(channel)
        }

        val notification = NotificationCompat.Builder(applicationContext, channelId)
            .setContentTitle("NetworkLogger")
            .setContentText("Logging network data in background...")
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .build()

        // Android 14+ requires explicit service type in ForegroundInfo
        return if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ForegroundInfo(
                1001,
                notification,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            )
        } else {
            ForegroundInfo(1001, notification)
        }
    }

    private fun logStorageInfo() {

        val path = Environment.getDataDirectory()
        val stat = StatFs(path.path)

        val blockSize = stat.blockSizeLong
        val totalBlocks = stat.blockCountLong
        val availableBlocks = stat.availableBlocksLong

        val totalStorage = totalBlocks * blockSize
        val freeStorage = availableBlocks * blockSize
        val usedStorage = totalStorage - freeStorage

        totalStorageGB = totalStorage / (1024f * 1024f * 1024f)
        freeStorageGB = freeStorage / (1024f * 1024f * 1024f)
        usedStorageGB = usedStorage / (1024f * 1024f * 1024f)

        Log.d("StorageInfo", "Total Storage: %.2f GB".format(totalStorageGB))
        Log.d("StorageInfo", "Used Storage: %.2f GB".format(usedStorageGB))
        Log.d("StorageInfo", "Free Storage: %.2f GB".format(freeStorageGB))

    }

    private fun logRamInfo() {

        val activityManager =
            applicationContext.getSystemService(Context.ACTIVITY_SERVICE)
                    as ActivityManager

        val memoryInfo = ActivityManager.MemoryInfo()

        activityManager.getMemoryInfo(memoryInfo)

        val totalRam = memoryInfo.totalMem
        val availableRam = memoryInfo.availMem
        val usedRam = totalRam - availableRam

        totalRamGB = totalRam / (1024f * 1024f * 1024f)
        availableRamGB = availableRam / (1024f * 1024f * 1024f)
        usedRamGB = usedRam / (1024f * 1024f * 1024f)

        Log.d("RAMInfo", "Total RAM: %.2f GB".format(totalRamGB))
        Log.d("RAMInfo", "Used RAM: %.2f GB".format(usedRamGB))
        Log.d("RAMInfo", "Available RAM: %.2f GB".format(availableRamGB))
    }


    private fun logBatteryInfo() {

        val batteryIntent = applicationContext.registerReceiver(
            null,
            IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        )

        val level = batteryIntent?.getIntExtra(
            BatteryManager.EXTRA_LEVEL,
            -1
        ) ?: -1

        val scale = batteryIntent?.getIntExtra(
            BatteryManager.EXTRA_SCALE,
            -1
        ) ?: -1

        batteryPercent = (level * 100) / scale

        Log.d("BatteryInfo", "Battery Percentage: $batteryPercent%")
    }


    private fun logTelecomInfo() {
        val telephonyManager =
            applicationContext.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager

        operatorName = telephonyManager.networkOperatorName  // safe, no permission needed

        networkType = if (ContextCompat.checkSelfPermission(
                applicationContext,
                android.Manifest.permission.READ_PHONE_STATE
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            when (telephonyManager.dataNetworkType) {
                TelephonyManager.NETWORK_TYPE_GPRS,
                TelephonyManager.NETWORK_TYPE_EDGE -> "2G"
                TelephonyManager.NETWORK_TYPE_UMTS,
                TelephonyManager.NETWORK_TYPE_HSDPA -> "3G"
                TelephonyManager.NETWORK_TYPE_LTE -> "4G"
                TelephonyManager.NETWORK_TYPE_NR -> "5G"
                else -> "Unknown"
            }
        } else {
            Log.w("NetworkWorker", "READ_PHONE_STATE not granted")
            "No Permission"
        }

        Log.d("TelecomInfo", "Operator: $operatorName")
        Log.d("TelecomInfo", "Network Type: $networkType")


        // At the end of logTelecomInfo(), after setting networkType:
        signalLevel = if (ContextCompat.checkSelfPermission(
                applicationContext, android.Manifest.permission.ACCESS_FINE_LOCATION
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            try {
                // Force a fresh cell info update before reading
                telephonyManager.requestCellInfoUpdate(
                    applicationContext.mainExecutor,
                    object : TelephonyManager.CellInfoCallback() {
                        override fun onCellInfo(cellInfoList: List<android.telephony.CellInfo>) {
                            // fresh data available but async — handled below
                        }
                        override fun onError(errorCode: Int, detail: Throwable?) {}
                    }
                )
                // Small pause to let modem respond
                Thread.sleep(300)

                val cellInfos = telephonyManager.allCellInfo
                val serving = cellInfos?.firstOrNull { it.isRegistered } ?: cellInfos?.firstOrNull()
                extractCellIdentity(serving)
                if (!cellInfos.isNullOrEmpty()) {
                    when (val cell = serving) {
                        is android.telephony.CellInfoNr -> {
                            val sig = cell.cellSignalStrength as android.telephony.CellSignalStrengthNr
                            "${sig.dbm} dBm"
                        }
                        is android.telephony.CellInfoLte -> {
                            "${cell.cellSignalStrength.rsrp} dBm"
                        }
                        else -> "N/A"
                    }
                } else "N/A"
            } catch (e: Exception) { "N/A" }
        } else "N/A"
    }

    private fun extractCellIdentity(cell: android.telephony.CellInfo?) {
        when (cell) {
            is android.telephony.CellInfoNr -> {
                val id = cell.cellIdentity as android.telephony.CellIdentityNr
                cellId = if (id.nci != Long.MAX_VALUE) id.nci.toString() else "N/A"
                tac = if (id.tac != Int.MAX_VALUE) id.tac.toString() else "N/A"
            }
            is android.telephony.CellInfoLte -> {
                // cellIdentity.ci is the ECI (E-UTRAN Cell Identifier): ECI = 256 * eNodeB ID + local Cell ID
                val eci = cell.cellIdentity.ci
                cellId = if (eci != Int.MAX_VALUE) (eci and 0xFF).toString() else "N/A"
                tac = if (cell.cellIdentity.tac != Int.MAX_VALUE) cell.cellIdentity.tac.toString() else "N/A"
            }
            is android.telephony.CellInfoWcdma -> {
                cellId = if (cell.cellIdentity.cid != Int.MAX_VALUE) cell.cellIdentity.cid.toString() else "N/A"
                tac = if (cell.cellIdentity.lac != Int.MAX_VALUE) cell.cellIdentity.lac.toString() else "N/A"
            }
            is android.telephony.CellInfoGsm -> {
                cellId = if (cell.cellIdentity.cid != Int.MAX_VALUE) cell.cellIdentity.cid.toString() else "N/A"
                tac = if (cell.cellIdentity.lac != Int.MAX_VALUE) cell.cellIdentity.lac.toString() else "N/A"
            }
            else -> { cellId = "N/A"; tac = "N/A" }
        }
        Log.d("TelecomInfo", "CellID: $cellId, TAC: $tac")
    }


    private fun isScreenOn(): Boolean {
        val powerManager = applicationContext.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        return powerManager.isInteractive
    }

    private fun saveBackgroundLog() {        try {
            val header = "Time,Battery,NetworkType,Operator,SignalLevel,CellID,TAC," +
                    "TotalStorage,UsedStorage,FreeStorage,TotalRAM,UsedRAM,AvailableRAM,ScreenOn\n"

            val timeStamp = SimpleDateFormat(
                "yyyy-MM-dd HH:mm:ss", Locale.getDefault()
            ).format(Date())
            val screenState = if (isScreenOn()) "ON" else "OFF"

            val logData = "$timeStamp,$batteryPercent,$networkType,$operatorName,$signalLevel,$cellId,$tac," +
                    "$totalStorageGB,$usedStorageGB,$freeStorageGB," +
                    "$totalRamGB,$usedRamGB,$availableRamGB,$screenState\n"

            LogStorage.appendRow(applicationContext, "background_logs", header, logData)

        } catch (e: Exception) {
            Log.e("CSV", "Error saving background CSV: ${e.message}", e)
        }
    }
}
