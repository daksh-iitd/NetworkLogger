// LoggingService.kt

package com.example.networklogger

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.TrafficStats
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.MediaStore
import android.provider.Settings
import android.telephony.CellIdentityNr
import android.telephony.CellInfoLte
import android.telephony.CellInfoNr
import android.telephony.CellSignalStrengthNr
import android.telephony.TelephonyManager
import android.util.Log
import android.widget.Toast
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.storage.FirebaseStorage
import com.google.firebase.storage.StorageMetadata
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// Owns the 5-second foreground logging loop. Runs as a real foreground service
// (unlike the old Handler on MainActivity) so it survives the app being backgrounded,
// e.g. while the user browses/streams in another app to generate network activity.
class LoggingService : Service() {

    companion object {
        const val ACTION_START = "com.example.networklogger.action.START_LOGGING"
        const val ACTION_STOP = "com.example.networklogger.action.STOP_LOGGING"
        const val ACTION_UPDATE = "com.example.networklogger.UPDATE"
        const val ACTION_STATUS_CHANGED = "com.example.networklogger.STATUS_CHANGED"

        const val EXTRA_NETWORK = "network"
        const val EXTRA_SIGNAL = "signal"
        const val EXTRA_LOCATION = "location"
        const val EXTRA_CELL_INFO = "cellInfo"
        const val EXTRA_THROUGHPUT = "throughput"
        const val EXTRA_DURATION = "duration"
        const val EXTRA_IS_RUNNING = "isRunning"

        private const val NOTIFICATION_ID = 2001
        private const val CHANNEL_ID = "logging_service_channel"

        @Volatile
        var isRunning = false
            private set
    }

    private lateinit var telephonyManager: TelephonyManager
    private lateinit var fusedLocationClient: FusedLocationProviderClient
    private val handler = Handler(Looper.getMainLooper())
    private val firebaseAuth by lazy { FirebaseAuth.getInstance() }
    private val firebaseStorage by lazy { FirebaseStorage.getInstance() }

    private var loggingStartTime = 0L

    private var currentLat = "N/A"
    private var currentLon = "N/A"
    private var currentAltitude = "N/A"
    private var currentSpeed = "N/A"
    private var currentAccuracy = "N/A"
    private var currentTime = "N/A"
    private var currentNetwork = "N/A"
    @Volatile private var latestDisplayInfo: android.telephony.TelephonyDisplayInfo? = null
    private var currentSignal = "N/A"
    private var currentOperator = "N/A"
    private var currentMCC = "N/A"
    private var currentMNC = "N/A"
    private var currentPCI = "N/A"
    private var currentTAC = "N/A"
    private var currentNCI = "N/A"
    private var currentRSRP = "N/A"
    private var currentRSRQ = "N/A"
    private var currentSINR = "N/A"
    private var currentNeighborCount = "0"
    private var currentBand = BandInfo.UNKNOWN
    // On 5G NSA the serving (registered) cell is the LTE anchor; the NR leg, when
    // the modem reports it at all, shows up as an unregistered CellInfoNr.
    private var currentNrLegBand = "N/A"
    private var currentDlKbps = "N/A"
    private var currentUlKbps = "N/A"
    private var lastRxBytes = -1L
    private var lastTxBytes = -1L
    private var lastThroughputSampleMs = 0L
    private var cellInfoDisplay = "Acquiring cell data..."

    private val logRunnable = object : Runnable {
        override fun run() {
            if (!isRunning) return
            updateMeasurements()
            updateThroughput()
            saveLog()
            broadcastUpdate()
            markAlive()
            handler.postDelayed(this, 5000)
        }
    }

    // Stamped on every successful tick; NetworkWorker's periodic watchdog check
    // compares this against "now" to notice a session that died silently (killed
    // by the OS, crashed, etc.) without anyone tapping Stop.
    private fun markAlive() {
        getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putLong(MainActivity.KEY_LAST_TICK_MS, System.currentTimeMillis())
            .apply()
    }

    override fun onCreate() {
        super.onCreate()
        telephonyManager = getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)
        createNotificationChannel()
        registerDisplayInfoListener()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopLogging()
        } else {
            startLogging()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacks(logRunnable)
        isRunning = false
    }

    private fun startLogging() {
        if (isRunning) return
        isRunning = true
        loggingStartTime = System.currentTimeMillis()
        LogStorage.beginSession(this, loggingStartTime)
        startForegroundCompat(buildNotification("Starting..."))
        broadcastStatus(true)
        getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(MainActivity.KEY_SESSION_ACTIVE, true)
            .putLong(MainActivity.KEY_LAST_TICK_MS, System.currentTimeMillis())
            .apply()
        handler.post(logRunnable)
        startBackgroundMonitoring()
    }

    private fun stopLogging() {
        if (!isRunning) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return
        }
        isRunning = false
        handler.removeCallbacks(logRunnable)
        broadcastStatus(false)
        getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(MainActivity.KEY_SESSION_ACTIVE, false)
            .apply()
        stopBackgroundMonitoring()
        // Branch on the mode this session was *started* in, not the current toggle.
        // Dev sessions were written straight into their own timestamped folder, so
        // there's nothing to move and nothing that a later production Stop could upload.
        if (LogStorage.isDevSession(this)) {
            Toast.makeText(
                applicationContext,
                "Dev mode: logs saved to ${LogStorage.devSessionFolder(this)}",
                Toast.LENGTH_LONG
            ).show()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        } else {
            updateNotification("Uploading logs...")
            uploadLogsToFirebaseStorage {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    // NetworkWorker's 15-minute background_logs.csv monitor is scoped to an
    // active logging session, same as network_logs.csv — it used to be enqueued
    // once on app launch and never cancelled, so it kept running forever
    // regardless of Start/Stop.
    private fun startBackgroundMonitoring() {
        val immediateRequest = androidx.work.OneTimeWorkRequestBuilder<NetworkWorker>().build()
        androidx.work.WorkManager.getInstance(this).enqueue(immediateRequest)

        val periodicRequest = androidx.work.PeriodicWorkRequestBuilder<NetworkWorker>(
            15, java.util.concurrent.TimeUnit.MINUTES
        ).build()
        androidx.work.WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "NetworkMonitoringWorker",
            androidx.work.ExistingPeriodicWorkPolicy.UPDATE,
            periodicRequest
        )
    }

    private fun stopBackgroundMonitoring() {
        androidx.work.WorkManager.getInstance(this).cancelUniqueWork("NetworkMonitoringWorker")
    }

    private fun startForegroundCompat(notification: Notification) {
        when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE ->
                startForeground(
                    NOTIFICATION_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION or ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                )
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ->
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            else ->
                startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "Live Logging", NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(status: String): Notification {
        val stopIntent = Intent(this, LoggingService::class.java).apply { action = ACTION_STOP }
        val stopPendingIntent = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val openAppIntent = packageManager.getLaunchIntentForPackage(packageName)
        val contentPendingIntent = PendingIntent.getActivity(
            this, 0, openAppIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("NetworkLogger — Logging active")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .setContentIntent(contentPendingIntent)
            .addAction(0, "Stop Logging", stopPendingIntent)
            .build()
    }

    private fun updateNotification(status: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, buildNotification(status))
    }

    private fun formattedDuration(): String {
        val elapsed = System.currentTimeMillis() - loggingStartTime
        return String.format(
            "%02d:%02d:%02d",
            elapsed / (1000 * 60 * 60),
            (elapsed / (1000 * 60)) % 60,
            (elapsed / 1000) % 60
        )
    }

    private fun broadcastUpdate() {
        val duration = formattedDuration()
        val intent = Intent(ACTION_UPDATE).apply {
            setPackage(packageName)
            putExtra(EXTRA_NETWORK, "Network: $currentNetwork")
            putExtra(EXTRA_SIGNAL, "Signal: $currentSignal")
            putExtra(EXTRA_LOCATION, "Location: $currentLat , $currentLon")
            putExtra(EXTRA_CELL_INFO, cellInfoDisplay)
            putExtra(EXTRA_THROUGHPUT, "DL: $currentDlKbps kbps   UL: $currentUlKbps kbps")
            putExtra(EXTRA_DURATION, duration)
        }
        sendBroadcast(intent)
        updateNotification("$duration • $currentNetwork • Signal: $currentSignal")
    }

    private fun broadcastStatus(running: Boolean) {
        val intent = Intent(ACTION_STATUS_CHANGED).apply {
            setPackage(packageName)
            putExtra(EXTRA_IS_RUNNING, running)
        }
        sendBroadcast(intent)
    }

    private fun getLocation() {
        if (ContextCompat.checkSelfPermission(
                this, android.Manifest.permission.ACCESS_FINE_LOCATION
            ) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) return

        fusedLocationClient.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, null)
            .addOnSuccessListener { location ->
                if (location != null) {
                    currentLat = "%.7f".format(location.latitude)
                    currentLon = "%.7f".format(location.longitude)
                    currentAltitude = "%.1f".format(location.altitude)
                    currentSpeed = "%.2f".format(location.speed)
                    currentAccuracy = "%.1f".format(location.accuracy)
                    Log.d("GPS", "Location: $currentLat, $currentLon")
                }
            }.addOnFailureListener { e ->
                Log.w("GPS", "Location fetch failed: ${e.message}")
            }
    }

    private fun getReadableNetworkType(type: Int): String {
        return when (type) {
            TelephonyManager.NETWORK_TYPE_GPRS,
            TelephonyManager.NETWORK_TYPE_EDGE -> "2G"
            TelephonyManager.NETWORK_TYPE_UMTS,
            TelephonyManager.NETWORK_TYPE_HSPA,
            TelephonyManager.NETWORK_TYPE_HSPAP -> "3G"
            TelephonyManager.NETWORK_TYPE_LTE -> "4G"
            TelephonyManager.NETWORK_TYPE_NR -> "5G"
            else -> "Unknown"
        }
    }

    // Registers a TelephonyDisplayInfo listener so the 5-second loop can distinguish
    // 5G NSA (LTE anchor + NR data — the common real-world 5G deployment) from plain
    // LTE and true 5G SA. TelephonyManager.networkType alone can't tell these apart:
    // on NSA it often still reports NETWORK_TYPE_LTE. Display info has no synchronous
    // getter, only a push callback, so we cache the latest value here.
    private fun registerDisplayInfoListener() {
        if (ContextCompat.checkSelfPermission(
                this, android.Manifest.permission.READ_PHONE_STATE
            ) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                telephonyManager.registerTelephonyCallback(
                    mainExecutor,
                    object : android.telephony.TelephonyCallback(),
                        android.telephony.TelephonyCallback.DisplayInfoListener {
                        override fun onDisplayInfoChanged(telephonyDisplayInfo: android.telephony.TelephonyDisplayInfo) {
                            latestDisplayInfo = telephonyDisplayInfo
                        }
                    }
                )
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                @Suppress("DEPRECATION")
                telephonyManager.listen(
                    object : android.telephony.PhoneStateListener() {
                        @Suppress("DEPRECATION")
                        override fun onDisplayInfoChanged(telephonyDisplayInfo: android.telephony.TelephonyDisplayInfo) {
                            latestDisplayInfo = telephonyDisplayInfo
                        }
                    },
                    @Suppress("DEPRECATION")
                    android.telephony.PhoneStateListener.LISTEN_DISPLAY_INFO_CHANGED
                )
            }
            // Below API 30, TelephonyDisplayInfo doesn't exist — falls back to networkType only.
        } catch (e: Exception) {
            Log.w("DisplayInfo", "Could not register display info listener: ${e.message}")
        }
    }

    private fun resolveNetworkLabel(): String {
        val displayInfo = latestDisplayInfo
        if (displayInfo != null) {
            when (displayInfo.overrideNetworkType) {
                android.telephony.TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_NR_NSA,
                android.telephony.TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_NR_NSA_MMWAVE ->
                    return "5G (NSA)"
                android.telephony.TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_LTE_CA ->
                    return "4G (CA)"
                android.telephony.TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_LTE_ADVANCED_PRO ->
                    return "4G (Advanced Pro)"
            }
            // OVERRIDE_NETWORK_TYPE_NONE: no override in effect — base type already
            // correctly reports 4G or true 5G SA, so fall through to it.
            return getReadableNetworkType(displayInfo.networkType)
        }
        return getReadableNetworkType(telephonyManager.networkType)
    }

    private fun updateMeasurements() {
        getLocation()
        currentNetwork = try {
            resolveNetworkLabel()
        } catch (e: Exception) {
            Log.w("Network", "Cannot read networkType: ${e.message}")
            "Unknown"
        }
        currentOperator = try { telephonyManager.networkOperatorName } catch (e: Exception) { "Unknown" }
        currentTime = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        getCellTowerInfo()
        getNeighborCellInfo()
    }

    private fun updateThroughput() {
        val rxBytes = TrafficStats.getTotalRxBytes()
        val txBytes = TrafficStats.getTotalTxBytes()
        val now = System.currentTimeMillis()

        if (rxBytes == TrafficStats.UNSUPPORTED.toLong() || txBytes == TrafficStats.UNSUPPORTED.toLong()) {
            currentDlKbps = "N/A"
            currentUlKbps = "N/A"
            return
        }

        if (lastThroughputSampleMs != 0L && lastRxBytes >= 0 && lastTxBytes >= 0) {
            val elapsedSeconds = (now - lastThroughputSampleMs) / 1000.0
            if (elapsedSeconds > 0) {
                val dlBytesDelta = (rxBytes - lastRxBytes).coerceAtLeast(0)
                val ulBytesDelta = (txBytes - lastTxBytes).coerceAtLeast(0)
                val dlKbps = (dlBytesDelta * 8.0) / 1000.0 / elapsedSeconds
                val ulKbps = (ulBytesDelta * 8.0) / 1000.0 / elapsedSeconds
                currentDlKbps = "%.1f".format(dlKbps)
                currentUlKbps = "%.1f".format(ulKbps)
            }
        }

        lastRxBytes = rxBytes
        lastTxBytes = txBytes
        lastThroughputSampleMs = now
    }

    private fun getNeighborCellInfo() {
        try {
            val cellInfoList = telephonyManager.allCellInfo
            if (cellInfoList.isNullOrEmpty()) {
                Log.d("NeighborCells", "No neighbor cells found")
                return
            }
            for (cellInfo in cellInfoList) {
                when (cellInfo) {
                    is CellInfoLte -> {
                        Log.d("NeighborCells", "LTE PCI: ${cellInfo.cellIdentity.pci}")
                        Log.d("NeighborCells", "LTE RSRP: ${cellInfo.cellSignalStrength.rsrp}")
                    }
                    is CellInfoNr -> {
                        val identity = cellInfo.cellIdentity as CellIdentityNr
                        val signal = cellInfo.cellSignalStrength as CellSignalStrengthNr
                        Log.d("NeighborCells", "5G PCI: ${identity.pci}")
                        Log.d("NeighborCells", "5G RSRP: ${signal.ssRsrp}")
                    }
                }
            }
        } catch (e: Exception) {
            Log.e("NeighborCells", "Error collecting neighbor cells", e)
        }
    }

    private fun getCellTowerInfo() {
        if (ContextCompat.checkSelfPermission(
                this, android.Manifest.permission.ACCESS_FINE_LOCATION
            ) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            cellInfoDisplay = "Cell Info: Location permission required."
            return
        }
        // Reset so a failed read never carries the previous cell's band into this row
        currentBand = BandInfo.UNKNOWN
        currentNrLegBand = "N/A"
        try {
            val cellInfos = telephonyManager.allCellInfo
            if (cellInfos.isNullOrEmpty()) {
                cellInfoDisplay = "Cell Info: Not Available"
                return
            }
            // allCellInfo does not guarantee the serving cell is first in the list —
            // must explicitly find the registered cell, otherwise a stale/neighbor
            // entry can get treated as serving and the RAT (e.g. 4G→5G) never updates.
            val servingCell = cellInfos.firstOrNull { it.isRegistered } ?: cellInfos[0]
            when (val cellInfo = servingCell) {
                is CellInfoLte -> {
                    val identity = cellInfo.cellIdentity
                    val signal = cellInfo.cellSignalStrength
                    val rsrp = signal.rsrp
                    val rsrq = if (signal.rsrq == Int.MAX_VALUE) "N/A" else "${signal.rsrq} dB"
                    // identity.ci is the ECI (E-UTRAN Cell Identifier): ECI = 256 * eNodeB ID + local Cell ID
                    val eci = identity.ci
                    val localCellId = if (eci != Int.MAX_VALUE) localCellIdFromEci(eci) else -1
                    val enbId = if (eci != Int.MAX_VALUE) eNodeBIdFromEci(eci) else -1
                    currentMCC = identity.mccString ?: "N/A"
                    currentMNC = identity.mncString ?: "N/A"
                    currentSignal = getRsrpSignalLabel(rsrp)
                    currentPCI = identity.pci.toString()
                    currentTAC = identity.tac.toString()
                    currentNCI = localCellId.toString()
                    currentRSRP = rsrp.toString()
                    currentRSRQ = if (signal.rsrq == Int.MAX_VALUE) "N/A" else signal.rsrq.toString()
                    currentSINR = "N/A"
                    currentNeighborCount = cellInfos.size.toString()
                    currentBand = BandInfo.of(identity)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                        cellInfos.firstOrNull { it is CellInfoNr && !it.isRegistered }?.let {
                            currentNrLegBand = BandInfo.of((it as CellInfoNr).cellIdentity as CellIdentityNr).band
                        }
                    }
                    val bandwidth = currentBand.bandwidthMhz?.let { " · %.0f MHz".format(it) } ?: ""
                    val nrLeg = if (currentNrLegBand != "N/A") "\n5G NSA leg: $currentNrLegBand" else ""
                    cellInfoDisplay =
                        "MCC: ${identity.mccString}\nMNC: ${identity.mncString}\n" +
                                "CID: $localCellId (eNB: $enbId, ECI: $eci)\nTAC: ${identity.tac}\n" +
                                "Band: ${currentBand.band}$bandwidth$nrLeg\n" +
                                "EARFCN: ${identity.earfcn}\nRSRP: $rsrp dBm\nRSRQ: $rsrq"
                }
                is CellInfoNr -> {
                    val identity = cellInfo.cellIdentity as CellIdentityNr
                    val signal = cellInfo.cellSignalStrength as CellSignalStrengthNr
                    val rsrq = when {
                        signal.ssRsrq != Int.MAX_VALUE -> "${signal.ssRsrq} dB"
                        signal.csiRsrq != Int.MAX_VALUE -> "${signal.csiRsrq} dB"
                        else -> "N/A"
                    }
                    val snr = when {
                        signal.ssSinr != Int.MAX_VALUE -> "${signal.ssSinr} dB"
                        signal.csiSinr != Int.MAX_VALUE -> "${signal.csiSinr} dB"
                        else -> "N/A"
                    }
                    currentMCC = identity.mccString ?: "N/A"
                    currentMNC = identity.mncString ?: "N/A"
                    currentSignal = getRsrpSignalLabel(signal.dbm)
                    currentPCI = identity.pci.toString()
                    currentTAC = identity.tac.toString()
                    currentNCI = identity.nci.toString()
                    currentRSRP = signal.dbm.toString()
                    currentRSRQ = rsrq.replace(" dB", "")
                    currentSINR = snr.replace(" dB", "")
                    currentNeighborCount = cellInfos.size.toString()
                    currentBand = BandInfo.of(identity)

                    val neighborDetails = StringBuilder()
                    for ((index, info) in cellInfos.withIndex()) {
                        when (info) {
                            is CellInfoNr -> {
                                val id = info.cellIdentity as CellIdentityNr
                                val sig = info.cellSignalStrength as CellSignalStrengthNr
                                neighborDetails.append("\nNeighbor ${index + 1}\nPCI: ${id.pci}\nNCI: ${id.nci}\nRSRP: ${sig.dbm} dBm\n")
                            }
                            is CellInfoLte -> {
                                val id = info.cellIdentity
                                val sig = info.cellSignalStrength
                                val neighborCellId = if (id.ci != Int.MAX_VALUE) localCellIdFromEci(id.ci) else -1
                                neighborDetails.append("\nNeighbor ${index + 1}\nPCI: ${id.pci}\nCID: $neighborCellId\nRSRP: ${sig.rsrp} dBm\n")
                            }
                        }
                    }
                    cellInfoDisplay =
                        "5G Cell\nBand: ${currentBand.band}\nNCI: ${identity.nci}\nPCI: ${identity.pci}\n" +
                                "TAC: ${identity.tac}\nRSRP: ${signal.dbm} dBm\n" +
                                "MCC: ${identity.mccString}\nMNC: ${identity.mncString}\n" +
                                "Operator: $currentOperator\nNRARFCN: ${identity.nrarfcn}\n" +
                                "RSRQ: $rsrq\nSINR: $snr\nTime: $currentTime\n" +
                                "Altitude: $currentAltitude m\nSpeed: $currentSpeed m/s\n" +
                                "GPS Accuracy: $currentAccuracy m\nNeighbor Cells: ${cellInfos.size}\n" +
                                "Level: ${signal.level}\n$neighborDetails"
                }
                else -> cellInfoDisplay = "Cell Info: Not Available"
            }
        } catch (e: Exception) {
            Log.e("CellInfo", "getCellTowerInfo failed: ${e.message}", e)
            cellInfoDisplay = "Cell Info: Error reading data"
        }
    }

    // LTE ECI (E-UTRAN Cell Identifier) = 256 * eNodeB ID + local Cell ID
    private fun eNodeBIdFromEci(eci: Int): Int = eci shr 8
    private fun localCellIdFromEci(eci: Int): Int = eci and 0xFF

    private fun getRsrpSignalLabel(rsrp: Int): String {
        return when {
            rsrp >= -80 -> "Very Strong"
            rsrp >= -90 -> "Strong"
            rsrp >= -100 -> "Medium"
            rsrp >= -110 -> "Weak"
            else -> "Very Weak"
        }
    }

    private fun isScreenOn(): Boolean {
        val powerManager = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        return powerManager.isInteractive
    }

    private fun saveLog() {
        val time = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        val screenState = if (isScreenOn()) "ON" else "OFF"
        val logLine = "$time,$currentLat,$currentLon,$currentNetwork,$currentSignal," +
                "$currentOperator,$currentMCC,$currentMNC,$currentPCI,$currentTAC,$currentNCI," +
                "$currentRSRP,$currentRSRQ,$currentSINR,$currentNeighborCount,$currentDlKbps,$currentUlKbps,$screenState," +
                "${currentBand.arfcn ?: "N/A"},${currentBand.band},${currentBand.source}," +
                "${currentBand.bandwidthMhz ?: "N/A"},$currentNrLegBand\n"
        // New columns go at the end so readers that select columns by name keep working
        val header = "time,lat,lon,network,signal,operator,mcc,mnc,pci,tac,nci,rsrp,rsrq,sinr,neighborCount," +
                "dlKbps,ulKbps,screenOn,arfcn,band,bandSource,bandwidthMHz,nrLegBand\n"
        try {
            LogStorage.appendRow(this, "network_logs", header, logLine)
        } catch (e: Exception) {
            Log.e("CSV", "saveLog() failed: ${e.message}", e)
        }
    }

    private fun getAppVersionInfo(): Pair<String, Long> {
        return try {
            val info = packageManager.getPackageInfo(packageName, 0)
            val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                info.longVersionCode
            } else {
                @Suppress("DEPRECATION")
                info.versionCode.toLong()
            }
            Pair(info.versionName ?: "unknown", versionCode)
        } catch (e: Exception) {
            Pair("unknown", -1L)
        }
    }

    private fun uploadLogsToFirebaseStorage(onComplete: () -> Unit) {
        val currentUser = firebaseAuth.currentUser
        if (currentUser == null) {
            firebaseAuth.signInAnonymously()
                .addOnSuccessListener { uploadLogsToFirebaseStorage(onComplete) }
                .addOnFailureListener { e ->
                    Log.e("StorageUpload", "Anonymous sign-in failed: ${e.message}", e)
                    Toast.makeText(applicationContext, "Firebase sign-in failed", Toast.LENGTH_LONG).show()
                    onComplete()
                }
            return
        }

        Toast.makeText(applicationContext, "Uploading logs to Firebase Storage...", Toast.LENGTH_SHORT).show()

        val deviceId = Settings.Secure.getString(
            contentResolver, Settings.Secure.ANDROID_ID
        ) ?: "unknown-device"
        val sessionId = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        val (appVersionName, appVersionCode) = getAppVersionInfo()
        val testerName = getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
            .getString(MainActivity.KEY_TESTER_NAME, "")
            ?.trim()
            ?.ifEmpty { "Unknown" } ?: "Unknown"

        val metadata = StorageMetadata.Builder()
            .setCustomMetadata("testerName", testerName)
            .setCustomMetadata("deviceId", deviceId)
            .setCustomMetadata("deviceModel", Build.MODEL)
            .setCustomMetadata("manufacturer", Build.MANUFACTURER)
            .setCustomMetadata("androidVersion", Build.VERSION.RELEASE)
            .setCustomMetadata("sdkInt", Build.VERSION.SDK_INT.toString())
            .setCustomMetadata("appVersionName", appVersionName)
            .setCustomMetadata("appVersionCode", appVersionCode.toString())
            .setCustomMetadata("sessionId", sessionId)
            .setCustomMetadata("uploadedAtEpochMs", System.currentTimeMillis().toString())
            .build()

        val filesToUpload = listOf("network_logs.csv", "background_logs.csv")
        var uploadedCount = 0
        var processedCount = 0

        fun onFileProcessed() {
            processedCount++
            if (processedCount == filesToUpload.size) {
                val message = when {
                    uploadedCount == filesToUpload.size -> "Uploaded both log files to Firebase Storage"
                    uploadedCount > 0 -> "Uploaded $uploadedCount log file(s) to Firebase Storage"
                    else -> "No logs found to upload"
                }
                Toast.makeText(applicationContext, message, Toast.LENGTH_LONG).show()
                onComplete()
            }
        }

        filesToUpload.forEach { fileName ->
            val localUri = findDownloadFileUri(fileName)
            if (localUri == null) {
                Log.w("StorageUpload", "File not found in Downloads: $fileName")
                onFileProcessed()
                return@forEach
            }
            val inputStream = contentResolver.openInputStream(localUri)
            if (inputStream == null) {
                Log.w("StorageUpload", "Cannot open file stream: $fileName")
                onFileProcessed()
                return@forEach
            }

            val storageRef = firebaseStorage.reference
                .child("logs/${currentUser.uid}/$deviceId/$sessionId/$fileName")
            storageRef.putStream(inputStream, metadata)
                .addOnSuccessListener {
                    uploadedCount++
                    Log.d("StorageUpload", "Uploaded file to Firebase Storage: $fileName")
                    resetLocalCsv(localUri)
                    onFileProcessed()
                }
                .addOnFailureListener { e ->
                    Log.e("StorageUpload", "Upload failed for $fileName: ${e.message}", e)
                    onFileProcessed()
                }
        }
    }

    private fun resetLocalCsv(uri: Uri) {
        try {
            contentResolver.delete(uri, null, null)
            Log.d("CSV", "Cleared local file after upload: $uri")
        } catch (e: Exception) {
            Log.w("CSV", "Failed to clear local file after upload: ${e.message}")
        }
    }

    private fun findDownloadFileUri(fileName: String): Uri? {
        val resolver = contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        return resolver.query(
            collection,
            arrayOf(MediaStore.Downloads._ID),
            "${MediaStore.Downloads.DISPLAY_NAME} = ?",
            arrayOf(fileName),
            null
        )?.use { cursor ->
            if (cursor.moveToFirst()) {
                ContentUris.withAppendedId(
                    collection,
                    cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID))
                )
            } else {
                null
            }
        }
    }
}
