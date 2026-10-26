// SessionDiagnostics.kt

package com.example.networklogger

import android.app.ActivityManager
import android.content.Context
import android.os.Build

// Why did logging stop? Android 11+ keeps a short history of why each of the app's
// processes ended (crash, low memory, "stop … due to installPackageLI" when Google Play
// services updates, …). Reading it after a restart and storing it on the session turns
// "status: died" into an actual cause, instead of digging it out with adb afterwards.
object SessionDiagnostics {

    private const val KEY_LAST_EXIT_SEEN_MS = "last_exit_seen_ms"
    const val KEY_SESSION_START_MS = "session_start_ms"

    // ApplicationExitInfo.REASON_* values (newer ones are compile-time ints, so no API check needed)
    private val REASONS = mapOf(
        0 to "UNKNOWN", 1 to "EXIT_SELF", 2 to "SIGNALED", 3 to "LOW_MEMORY", 4 to "CRASH",
        5 to "CRASH_NATIVE", 6 to "ANR", 7 to "INITIALIZATION_FAILURE", 8 to "PERMISSION_CHANGE",
        9 to "EXCESSIVE_RESOURCE_USAGE", 10 to "USER_REQUESTED", 11 to "USER_STOPPED",
        12 to "DEPENDENCY_DIED", 13 to "OTHER", 14 to "FREEZER", 15 to "PACKAGE_STATE_CHANGE",
        16 to "PACKAGE_UPDATED",
    )

    // Process exits during the current session that haven't been recorded yet, oldest first.
    // Each exit is returned once, whichever of the watchdog or a resumed service asks first.
    fun newProcessExits(context: Context): List<Map<String, Any?>> {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return emptyList()
        val prefs = prefs(context)
        val since = maxOf(prefs.getLong(KEY_LAST_EXIT_SEEN_MS, 0L), prefs.getLong(KEY_SESSION_START_MS, 0L))
        val exits = try {
            context.getSystemService(ActivityManager::class.java)
                .getHistoricalProcessExitReasons(context.packageName, 0, 16)
                .filter { it.timestamp > since }
                .sortedBy { it.timestamp }
        } catch (e: Exception) {
            return emptyList()
        }
        if (exits.isEmpty()) return emptyList()
        prefs.edit().putLong(KEY_LAST_EXIT_SEEN_MS, exits.last().timestamp).apply()
        return exits.map {
            event(
                "process_exit",
                "reason" to (REASONS[it.reason] ?: "REASON_${it.reason}"),
                "description" to it.description,
                "importance" to it.importance,
                atMs = it.timestamp,
            )
        }
    }

    fun event(type: String, vararg extra: Pair<String, Any?>, atMs: Long = System.currentTimeMillis()) =
        mapOf("type" to type, "atMs" to atMs) + extra

    private fun prefs(context: Context) =
        context.getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
}
