// MainActivity.kt

package com.example.networklogger

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.telephony.PhoneStateListener
import android.telephony.SignalStrength
import android.telephony.TelephonyManager
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.cardview.widget.CardView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.File

class MainActivity : AppCompatActivity() {

    companion object {
        // Shared with LoggingService, which reads the saved name for upload metadata.
        const val PREFS_NAME = "network_logger_prefs"
        const val KEY_TESTER_NAME = "tester_name"

        // Shared with LoggingService (writer) and NetworkWorker (watchdog reader).
        // LoggingService marks a session active/inactive and stamps every successful
        // tick; NetworkWorker's periodic run checks whether an "active" session has
        // gone stale (the service died without anyone tapping Stop) and alerts.
        const val KEY_SESSION_ACTIVE = "session_active"
        const val KEY_LAST_TICK_MS = "last_tick_ms"

        // Developer mode: logs are written into a timestamped folder under Downloads
        // instead of being streamed to Firestore. Defaults to ON, so a fresh install
        // never uploads until someone explicitly switches to production.
        const val KEY_DEV_MODE = "dev_mode"

        private const val KEY_ASKED_BACKGROUND_LOCATION = "asked_background_location"
        private const val REQUEST_PERMISSIONS = 1
        private const val REQUEST_BACKGROUND_LOCATION = 2

        // The public build has no dev mode at all: always production, whatever an
        // earlier install may have left in preferences.
        fun isDevMode(context: Context): Boolean =
            BuildConfig.DEV_MODE_AVAILABLE &&
                context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                    .getBoolean(KEY_DEV_MODE, true)
    }

    private lateinit var locationText: TextView
    private lateinit var networkText: TextView
    private lateinit var signalText: TextView
    private lateinit var cellInfoText: TextView
    private lateinit var throughputText: TextView
    private lateinit var rootStatusText: TextView
    private lateinit var rootStatusText2: TextView
    private lateinit var loggingDurationText: TextView
    private lateinit var networkLogPathText: TextView
    private lateinit var backgroundLogPathText: TextView
    private lateinit var telephonyManager: TelephonyManager
    private lateinit var loggingButton: Button

    private var isLogging = false

    // Reflects live updates from LoggingService, which owns the actual 5-second
    // logging loop as a foreground service so it survives the app being backgrounded
    // (e.g. during a browsing/streaming test).
    private val updateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                LoggingService.ACTION_UPDATE -> {
                    intent.getStringExtra(LoggingService.EXTRA_NETWORK)?.let { networkText.text = it }
                    intent.getStringExtra(LoggingService.EXTRA_SIGNAL)?.let { signalText.text = it }
                    intent.getStringExtra(LoggingService.EXTRA_LOCATION)?.let { locationText.text = it }
                    intent.getStringExtra(LoggingService.EXTRA_CELL_INFO)?.let { cellInfoText.text = it }
                    intent.getStringExtra(LoggingService.EXTRA_THROUGHPUT)?.let { throughputText.text = it }
                    intent.getStringExtra(LoggingService.EXTRA_DURATION)?.let { loggingDurationText.text = it }
                }
                LoggingService.ACTION_STATUS_CHANGED -> {
                    isLogging = intent.getBooleanExtra(LoggingService.EXTRA_IS_RUNNING, false)
                    updateLoggingButton()
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        locationText        = findViewById(R.id.locationText)
        networkText         = findViewById(R.id.networkText)
        signalText          = findViewById(R.id.signalText)
        cellInfoText        = findViewById(R.id.cellInfoText)
        throughputText      = findViewById(R.id.throughputText)
        rootStatusText      = findViewById(R.id.rootStatusText)
        rootStatusText2     = findViewById(R.id.rootStatusText2)
        loggingDurationText = findViewById(R.id.loggingDurationText)
        networkLogPathText  = findViewById(R.id.networkLogPathText)
        backgroundLogPathText = findViewById(R.id.backgroundLogPathText)

        loggingButton = findViewById(R.id.loggingButton)
        val testerNameInput = findViewById<EditText>(R.id.testerNameInput)
        val saveNameButton = findViewById<Button>(R.id.saveNameButton)

        telephonyManager = getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager

        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        testerNameInput.setText(prefs.getString(KEY_TESTER_NAME, ""))
        saveNameButton.setOnClickListener {
            val name = testerNameInput.text.toString().trim()
            prefs.edit().putString(KEY_TESTER_NAME, name).apply()
            Toast.makeText(
                this,
                if (name.isEmpty()) "Tester name cleared" else "Tester name saved: $name",
                Toast.LENGTH_SHORT
            ).show()
        }

        // ── ROOT DETECTION ──────────────────────────────────────────────
        applyRootDetection()
        // ────────────────────────────────────────────────────────────────

        val devModeButton = findViewById<Button>(R.id.devModeButton)
        devModeButton.setOnClickListener {
            // The mode decides what happens to the files on Stop, so don't let it
            // flip mid-session and surprise the tester with an upload (or lack of one).
            if (isLogging) {
                Toast.makeText(this, "Stop logging before switching modes", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val devMode = !isDevMode(this)
            prefs.edit().putBoolean(KEY_DEV_MODE, devMode).apply()
            applyModeColors(devMode)
            Toast.makeText(
                this,
                if (devMode) "Developer mode ON — logs stay on this device"
                else "Production mode — logs stream to the cloud every minute",
                Toast.LENGTH_SHORT
            ).show()
        }
        applyModeColors(isDevMode(this))
        if (!BuildConfig.DEV_MODE_AVAILABLE) {
            findViewById<View>(R.id.modeBar).visibility = View.GONE
        }

        loggingButton.setOnClickListener {
            if (!isLogging) {
                loggingDurationText.text = "00:00:00"
                Toast.makeText(this, "Logs are started", Toast.LENGTH_SHORT).show()
            }
            ContextCompat.startForegroundService(
                this,
                Intent(this, LoggingService::class.java).apply {
                    action = if (isLogging) LoggingService.ACTION_STOP else LoggingService.ACTION_START
                }
            )
            // Flip right away so a quick second tap means "stop", not another "start";
            // the service's status broadcast confirms (or corrects) it moments later.
            isLogging = !isLogging
            updateLoggingButton()
        }

        CloudSync.init()
        requestPermissions()
        setupSignalListener()
        requestBatteryOptimizationExemption()
    }

    override fun onStart() {
        super.onStart()
        isLogging = LoggingService.isRunning
        updateLoggingButton()
        val filter = IntentFilter().apply {
            addAction(LoggingService.ACTION_UPDATE)
            addAction(LoggingService.ACTION_STATUS_CHANGED)
        }
        ContextCompat.registerReceiver(this, updateReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    override fun onStop() {
        super.onStop()
        unregisterReceiver(updateReceiver)
    }

    private fun updateLoggingButton() {
        loggingButton.text = if (isLogging) "⏹  STOP LOGGING" else "▶  START LOGGING"
        loggingButton.backgroundTintList =
            ColorStateList.valueOf(Color.parseColor(if (isLogging) "#EF4444" else "#10B981"))
    }

    // ─────────────────────────────────────────────────────────────────────────
    // DEV MODE THEME — production keeps the original navy/indigo palette;
    // developer mode switches to amber/brown so the mode is obvious at a glance
    // ─────────────────────────────────────────────────────────────────────────

    private fun applyModeColors(devMode: Boolean) {
        val background = Color.parseColor(if (devMode) "#1A1206" else "#0A0E1A")
        val header     = Color.parseColor(if (devMode) "#3D2606" else "#111827")
        val card       = Color.parseColor(if (devMode) "#2B1D0A" else "#161D2F")
        val pathsCard  = Color.parseColor(if (devMode) "#221605" else "#0F172A")
        val accent     = Color.parseColor(if (devMode) "#F59E0B" else "#6366F1")
        val modeBar    = Color.parseColor(if (devMode) "#F59E0B" else "#1E293B")
        val modeText   = Color.parseColor(if (devMode) "#1C1100" else "#9CA3AF")
        val buttonBg   = Color.parseColor(if (devMode) "#1C1100" else "#6366F1")

        findViewById<View>(R.id.rootScroll).setBackgroundColor(background)
        findViewById<View>(R.id.headerBar).setBackgroundColor(header)
        findViewById<View>(R.id.modeBar).setBackgroundColor(modeBar)
        findViewById<TextView>(R.id.modeText).apply {
            text = if (devMode) "DEVELOPER MODE\nLogs stay on this device"
                   else "PRODUCTION MODE\nLogs stream to the cloud every minute"
            setTextColor(modeText)
        }
        findViewById<Button>(R.id.devModeButton).apply {
            text = if (devMode) "Switch to Production" else "Switch to Dev Mode"
            backgroundTintList = ColorStateList.valueOf(buttonBg)
        }

        networkLogPathText.text = if (devMode)
            "Each session  →  /storage/emulated/0/Download/NetworkLogger/session_<start time>/"
        else
            "Samples  →  Firestore, sent every minute (queued while offline)"
        backgroundLogPathText.text = if (devMode)
            "network_logs_<time>.csv + background_logs_<time>.csv"
        else
            "No CSV files are kept on the phone in production mode"

        recolorTree(findViewById(R.id.rootScroll), card, pathsCard, accent)
    }

    private fun recolorTree(view: View, card: Int, pathsCard: Int, accent: Int) {
        when {
            view is CardView -> view.setCardBackgroundColor(if (view.tag == "pathsCard") pathsCard else card)
            view.tag == "accent" -> view.setBackgroundColor(accent)
        }
        if (view is ViewGroup) {
            for (i in 0 until view.childCount) recolorTree(view.getChildAt(i), card, pathsCard, accent)
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // ROOT DETECTION — runs all 7 checks, updates both badges with reason list
    // ─────────────────────────────────────────────────────────────────────────

    private fun applyRootDetection() {
        // Run each check independently so we can report which ones fired
        val detectionReasons = mutableListOf<String>()
        if (checkSuBinaries())       detectionReasons.add("su binary")
        if (checkRootPackages())     detectionReasons.add("root app")
        if (checkBuildTags())        detectionReasons.add("test-keys")
        if (checkDangerousProps())   detectionReasons.add("sys props")
        if (checkRWPaths())          detectionReasons.add("rw /system")
        if (checkRootCloakingApps()) detectionReasons.add("cloak app")
        if (tryExecuteSu())          detectionReasons.add("su exec")

        val isRooted = detectionReasons.isNotEmpty()

        Log.d("RootCheck", "Rooted: $isRooted | Triggers: $detectionReasons")

        if (isRooted) {
            // Header badge → red
            rootStatusText.text = "Rooted"
            rootStatusText.setTextColor(Color.parseColor("#EF4444"))
            rootStatusText.background =
                ContextCompat.getDrawable(this, R.drawable.badge_red)

            // Device card → shows which method triggered
            rootStatusText2.text = "Rooted\n(${detectionReasons.joinToString(", ")})"
            rootStatusText2.setTextColor(Color.parseColor("#EF4444"))

        } else {
            // Header badge → green (default)
            rootStatusText.text = "Non-Rooted"
            rootStatusText.setTextColor(Color.parseColor("#10B981"))
            rootStatusText.background =
                ContextCompat.getDrawable(this, R.drawable.badge_green)

            // Device card
            rootStatusText2.text = "Non-Rooted"
            rootStatusText2.setTextColor(Color.parseColor("#10B981"))
        }
    }

    private fun checkSuBinaries(): Boolean {
        val paths = arrayOf(
            "/system/bin/su", "/system/xbin/su", "/sbin/su", "/system/su",
            "/system/bin/.ext/su", "/system/usr/we-need-root/su",
            "/system/app/Superuser.apk", "/data/local/su",
            "/data/local/xbin/su", "/data/local/bin/su",
            "/system/sd/xbin/su", "/system/bin/failsafe/su"
        )
        for (path in paths) {
            try {
                if (File(path).exists()) {
                    Log.d("RootCheck", "Su binary found at: $path")
                    return true
                }
            } catch (e: Exception) {
                Log.w("RootCheck", "Cannot check $path: ${e.message}")
            }
        }
        return false
    }

    private fun checkRootPackages(): Boolean {
        val rootPackages = arrayOf(
            "com.topjohnwu.magisk",
            "com.noshufou.android.su",
            "com.noshufou.android.su.elite",
            "eu.chainfire.supersu",
            "com.koushikdutta.superuser",
            "com.thirdparty.superuser",
            "com.yellowes.su",
            "com.kingroot.kinguser",
            "com.kingo.root",
            "com.smedialink.oneclickroot",
            "com.zhiqupk.root.global",
            "com.alephzain.framaroot"
        )
        for (pkg in rootPackages) {
            try {
                packageManager.getPackageInfo(pkg, 0)
                Log.d("RootCheck", "Root package found: $pkg")
                return true
            } catch (e: Exception) { }
        }
        return false
    }

    private fun checkBuildTags(): Boolean {
        return try {
            val tags = android.os.Build.TAGS
            val isTestKeys = tags != null && tags.contains("test-keys")
            if (isTestKeys) Log.d("RootCheck", "test-keys build tag found")
            isTestKeys
        } catch (e: Exception) { false }
    }

    private fun checkDangerousProps(): Boolean {
        val dangerousProps = mapOf(
            "ro.debuggable"    to "1",
            "ro.secure"        to "0",
            "ro.build.type"    to "eng",
            "service.adb.root" to "1"
        )
        for ((prop, dangerousValue) in dangerousProps) {
            try {
                val process = Runtime.getRuntime().exec(arrayOf("getprop", prop))
                val value = process.inputStream.bufferedReader().readLine()?.trim()
                if (value == dangerousValue) {
                    Log.d("RootCheck", "Dangerous prop: $prop = $value")
                    return true
                }
            } catch (e: Exception) {
                Log.w("RootCheck", "Cannot read prop $prop: ${e.message}")
            }
        }
        return false
    }

    private fun checkRWPaths(): Boolean {
        val rwPaths = arrayOf(
            "/system", "/system/bin", "/system/sbin",
            "/system/xbin", "/vendor/bin", "/sbin", "/etc"
        )
        return try {
            val process = Runtime.getRuntime().exec("mount")
            val output = process.inputStream.bufferedReader().readText()
            rwPaths.any { path ->
                val regex = Regex("""$path\s+\S+\s+\S+\s+\(rw""")
                regex.containsMatchIn(output).also {
                    if (it) Log.d("RootCheck", "RW path found: $path")
                }
            }
        } catch (e: Exception) {
            Log.w("RootCheck", "mount check failed: ${e.message}")
            false
        }
    }

    private fun checkRootCloakingApps(): Boolean {
        val cloakPackages = arrayOf(
            "com.devadvance.rootcloak",
            "com.devadvance.rootcloakplus",
            "de.robv.android.xposed.installer",
            "com.saurik.substrate",
            "com.zachspong.temprootremovejb",
            "com.amphoras.hidemyroot",
            "com.formyhm.hiderootPremium",
            "com.amphoras.hidemyrootadfree"
        )
        for (pkg in cloakPackages) {
            try {
                packageManager.getPackageInfo(pkg, 0)
                Log.d("RootCheck", "Cloaking app found: $pkg")
                return true
            } catch (e: Exception) { }
        }
        return false
    }

    private fun tryExecuteSu(): Boolean {
        return try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", "id"))
            val output = process.inputStream.bufferedReader().readLine() ?: ""
            val isRoot = output.contains("uid=0")
            if (isRoot) Log.d("RootCheck", "su execution succeeded: $output")
            isRoot
        } catch (e: Exception) {
            Log.w("RootCheck", "su execution blocked (expected on non-rooted): ${e.message}")
            false
        }
    }

    // ─────────────────────────────────────────────────────────────────────────

    private fun requestBatteryOptimizationExemption() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                val pm = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
                if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                    val intent = Intent(
                        android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
                    ).apply { data = android.net.Uri.parse("package:$packageName") }
                    startActivity(intent)
                }
            } catch (e: Exception) {
                Log.w("BatteryOpt", "Battery optimization exemption not available: ${e.message}")
            }
        }
    }

    private fun requestPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.READ_PHONE_STATE
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        ActivityCompat.requestPermissions(this, permissions.toTypedArray(), REQUEST_PERMISSIONS)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_PERMISSIONS) requestBackgroundLocation()
    }

    // "Allow all the time" location lets the watchdog resume a session Android killed:
    // a service restarted from the background can't read GPS or cells without it. It has
    // to be asked for on its own, after foreground location (Android 11+ opens Settings).
    private fun requestBackgroundLocation() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        val granted = { p: String -> ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED }
        if (!granted(Manifest.permission.ACCESS_FINE_LOCATION) || granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)) return
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_ASKED_BACKGROUND_LOCATION, false)) return
        prefs.edit().putBoolean(KEY_ASKED_BACKGROUND_LOCATION, true).apply()
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Keep logging after interruptions")
            .setMessage("If Android stops NetworkLogger during a session (for example when Google Play " +
                    "services updates), it can restart logging by itself, but only with location access " +
                    "\"Allow all the time\". Choose that option on the next screen.")
            .setPositiveButton("Continue") { _, _ ->
                ActivityCompat.requestPermissions(
                    this, arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION), REQUEST_BACKGROUND_LOCATION
                )
            }
            .setNegativeButton("Not now", null)
            .show()
    }

    private fun setupSignalListener() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                telephonyManager.registerTelephonyCallback(
                    mainExecutor,
                    object : android.telephony.TelephonyCallback(),
                        android.telephony.TelephonyCallback.SignalStrengthsListener {
                        override fun onSignalStrengthsChanged(signalStrength: SignalStrength) {
                            if (!isLogging) {
                                signalText.text = "Signal: " + when (signalStrength.level) {
                                    0 -> "Very Weak"; 1 -> "Weak"; 2 -> "Medium"
                                    3 -> "Strong";   4 -> "Very Strong"; else -> "Unknown"
                                }
                            }
                        }
                    }
                )
            } else {
                @Suppress("DEPRECATION")
                telephonyManager.listen(
                    object : PhoneStateListener() {
                        @Suppress("DEPRECATION")
                        override fun onSignalStrengthsChanged(signalStrength: SignalStrength) {
                            super.onSignalStrengthsChanged(signalStrength)
                            if (!isLogging) {
                                signalText.text = "Signal: " + when (signalStrength.level) {
                                    0 -> "Very Weak"; 1 -> "Weak"; 2 -> "Medium"
                                    3 -> "Strong";   4 -> "Very Strong"; else -> "Unknown"
                                }
                            }
                        }
                    },
                    @Suppress("DEPRECATION")
                    PhoneStateListener.LISTEN_SIGNAL_STRENGTHS
                )
            }
        } catch (e: Exception) {
            Log.w("SignalListener", "Signal listener setup failed: ${e.message}")
        }
    }

}
