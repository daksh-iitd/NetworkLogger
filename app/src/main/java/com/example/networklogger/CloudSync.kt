// CloudSync.kt

package com.example.networklogger

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.util.Log
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.DocumentReference
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.SetOptions
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// Streams production sessions to Cloud Firestore while they run, replacing the old
// "write Download/*.csv, upload the files on Stop" flow. Dev sessions never come here.
//
//   users/{uid}/sessions/{sessionId}                 ← tester/device/app metadata, start/end
//   users/{uid}/sessions/{sessionId}/batches/{seq}   ← one doc per flush, `rows` = 5 s samples
//   users/{uid}/sessions/{sessionId}/background/…    ← one doc per NetworkWorker run
//
// Firestore persists pending writes on disk and sends them once the phone is back
// online (also after an app restart), so a flush while out of coverage is not lost.
// Samples are batched rather than written one per document to keep the write count
// (and the radio wake-ups) down.
object CloudSync {

    private const val TAG = "CloudSync"
    const val FLUSH_INTERVAL_MS = 60_000L

    private const val KEY_CLOUD_SESSION_ID = "cloud_session_id"
    // Next batch number, persisted so a session resumed in a new process continues the
    // numbering instead of colliding with batch documents that already exist
    private const val KEY_BATCH_SEQ = "cloud_batch_seq"

    // The project's Firestore database is a named one, not "(default)"
    private const val DATABASE_ID = "android-telecom-database"

    private val db by lazy { FirebaseFirestore.getInstance(DATABASE_ID) }
    private val auth by lazy { FirebaseAuth.getInstance() }

    private val pendingRows = mutableListOf<Map<String, Any?>>()
    private var batchSeq = 0
    private var sessionInfo: Map<String, Any?> = emptyMap()
    private var sessionDocWritten = false

    private val waitingForUser = mutableListOf<(String) -> Unit>()
    private var signingIn = false

    // Touching Firestore at launch lets writes queued by an earlier run (phone was
    // offline when the app died) resume uploading without waiting for a new session.
    fun init() {
        db
    }

    fun beginSession(context: Context, startTimeMs: Long) {
        val deviceId = deviceId(context)
        val startStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date(startTimeMs))
        val sessionId = "${deviceId}_$startStamp"
        prefs(context).edit().putString(KEY_CLOUD_SESSION_ID, sessionId).putInt(KEY_BATCH_SEQ, 0).apply()

        val (appVersionName, appVersionCode) = appVersionInfo(context)
        val testerName = prefs(context).getString(MainActivity.KEY_TESTER_NAME, "")
            ?.trim()
            ?.ifEmpty { "Unknown" } ?: "Unknown"

        synchronized(this) {
            pendingRows.clear()
            batchSeq = 0
            sessionDocWritten = false
            sessionInfo = mapOf(
                "sessionId" to sessionId,
                "startStamp" to startStamp,
                "testerName" to testerName,
                "deviceId" to deviceId,
                "deviceModel" to Build.MODEL,
                "manufacturer" to Build.MANUFACTURER,
                "androidVersion" to Build.VERSION.RELEASE,
                "sdkInt" to Build.VERSION.SDK_INT,
                "appVersionName" to appVersionName,
                "appVersionCode" to appVersionCode,
                "startedAtMs" to startTimeMs,
                "flushIntervalMs" to FLUSH_INTERVAL_MS,
                "status" to "active",
            )
        }
        withUser { uid -> writeSessionDocIfNeeded(uid, sessionId) }
    }

    // Continues the session already in progress after the logging service was restarted
    // (by Android, or by NetworkWorker's watchdog) in a fresh process: same session id,
    // batch numbering picks up where it stopped, and the restart is recorded as events.
    fun resumeSession(context: Context, events: List<Map<String, Any?>>) {
        val sessionId = currentSessionId(context) ?: return
        synchronized(this) {
            pendingRows.clear()
            batchSeq = prefs(context).getInt(KEY_BATCH_SEQ, 0)
            sessionDocWritten = true
            sessionInfo = mapOf("sessionId" to sessionId)
        }
        writeSession(sessionId, mapOf("status" to "active", "restarts" to FieldValue.increment(1)), events)
    }

    // Diagnostic events (process exits, service destroyed, app swiped away, restarts) are
    // appended to the session document's `events` array.
    fun recordEvents(context: Context, events: List<Map<String, Any?>>) {
        if (events.isEmpty()) return
        val sessionId = currentSessionId(context) ?: return
        writeSession(sessionId, emptyMap(), events)
    }

    private fun writeSession(sessionId: String, fields: Map<String, Any?>, events: List<Map<String, Any?>>) {
        withUser { uid ->
            val update = if (events.isEmpty()) fields
                         else fields + ("events" to FieldValue.arrayUnion(*events.toTypedArray()))
            sessionRef(uid, sessionId).set(update, SetOptions.merge())
                .addOnFailureListener { e -> Log.e(TAG, "Session update rejected: ${e.message}", e) }
        }
    }

    @Synchronized
    fun addSample(row: Map<String, Any?>) {
        pendingRows += row
    }

    // Called every FLUSH_INTERVAL_MS by LoggingService. Rows stay in memory until a
    // Firebase user exists (anonymous sign-in needs the network the very first time).
    fun flush(context: Context) {
        val sessionId = currentSessionId(context) ?: return
        withUser { uid ->
            writeSessionDocIfNeeded(uid, sessionId)
            val rows: List<Map<String, Any?>>
            val seq: Int
            synchronized(this) {
                if (pendingRows.isEmpty()) return@withUser
                rows = pendingRows.toList()
                pendingRows.clear()
                seq = batchSeq++
            }
            // commit(), not apply(): if the process dies right after this, the next number
            // must already be on disk, or a resumed session would reuse this batch's id
            prefs(context).edit().putInt(KEY_BATCH_SEQ, seq + 1).commit()
            // Zero-padded seq as the doc id keeps batches ordered and makes a re-sent
            // write land on the same document instead of duplicating rows.
            sessionRef(uid, sessionId).collection("batches").document("%06d".format(seq))
                .set(
                    mapOf(
                        "seq" to seq,
                        "rowCount" to rows.size,
                        "firstTs" to rows.first()["ts"],
                        "lastTs" to rows.last()["ts"],
                        "uploadedAt" to FieldValue.serverTimestamp(),
                        "rows" to rows,
                    )
                )
                .addOnFailureListener { e -> Log.e(TAG, "Batch $seq rejected: ${e.message}", e) }
        }
    }

    // Final flush plus end-of-session stamp. Also used by NetworkWorker's watchdog
    // (status "died"), where nothing is left in memory and only the stamp matters.
    fun endSession(context: Context, endTimeMs: Long, status: String = "ended") {
        val sessionId = currentSessionId(context) ?: return
        flush(context)
        withUser { uid ->
            val fields = mutableMapOf<String, Any?>(
                "endedAtMs" to endTimeMs,
                "endedAt" to FieldValue.serverTimestamp(),
                "status" to status,
            )
            // Only this process's own session has a meaningful counter (not so after
            // the process was killed and the watchdog is the one ending it)
            synchronized(this) {
                if (sessionInfo["sessionId"] == sessionId) fields["batchCount"] = batchSeq
            }
            // merge: works whether or not the session doc reached the server yet
            sessionRef(uid, sessionId).set(fields, SetOptions.merge()).addOnFailureListener { e -> Log.e(TAG, "Session end rejected: ${e.message}", e) }
        }
    }

    fun addBackgroundRow(context: Context, row: Map<String, Any?>) {
        val sessionId = currentSessionId(context) ?: return
        withUser { uid ->
            sessionRef(uid, sessionId).collection("background")
                .add(row + ("uploadedAt" to FieldValue.serverTimestamp()))
                .addOnFailureListener { e -> Log.e(TAG, "Background row rejected: ${e.message}", e) }
        }
    }

    private fun writeSessionDocIfNeeded(uid: String, sessionId: String) {
        val info = synchronized(this) {
            if (sessionDocWritten || sessionInfo["sessionId"] != sessionId) return
            sessionDocWritten = true
            sessionInfo
        }
        sessionRef(uid, sessionId)
            .set(info + mapOf("uid" to uid, "startedAt" to FieldValue.serverTimestamp()), SetOptions.merge())
            .addOnFailureListener { e -> Log.e(TAG, "Session doc rejected: ${e.message}", e) }
    }

    private fun withUser(block: (String) -> Unit) {
        auth.currentUser?.let { block(it.uid); return }
        synchronized(this) {
            waitingForUser += block
            if (signingIn) return
            signingIn = true
        }
        auth.signInAnonymously()
            .addOnSuccessListener { result ->
                val uid = result.user?.uid
                val blocks = synchronized(this) {
                    signingIn = false
                    waitingForUser.toList().also { waitingForUser.clear() }
                }
                if (uid != null) blocks.forEach { it(uid) }
            }
            .addOnFailureListener { e ->
                // Probably offline on first use; rows stay pending for the next flush.
                Log.w(TAG, "Anonymous sign-in failed: ${e.message}")
                synchronized(this) {
                    signingIn = false
                    waitingForUser.clear()
                }
            }
    }

    private fun sessionRef(uid: String, sessionId: String): DocumentReference =
        db.collection("users").document(uid).collection("sessions").document(sessionId)

    private fun currentSessionId(context: Context): String? =
        prefs(context).getString(KEY_CLOUD_SESSION_ID, null)

    private fun deviceId(context: Context): String =
        Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown-device"

    private fun appVersionInfo(context: Context): Pair<String, Long> {
        return try {
            val info = context.packageManager.getPackageInfo(context.packageName, 0)
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

    // Values are formatted with the default locale ("%.7f"), which uses a decimal
    // comma in some regions; store real numbers so the server needn't guess.
    fun num(value: String): Number? =
        value.toLongOrNull() ?: value.replace(',', '.').toDoubleOrNull()

    private fun prefs(context: Context) =
        context.getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
}
