// LogStorage.kt

package com.example.networklogger

import android.content.ContentResolver
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// Session mode plus the developer-mode CSV files, shared by LoggingService
// (network_logs) and NetworkWorker (background_logs).
//
// The mode is captured once when a session starts, so dev-mode data can never end
// up in the cloud:
//  - production session → streamed to Firestore by CloudSync, no CSV on the phone
//  - developer session  → Download/NetworkLogger/session_<start>/<base>_<start>.csv,
//                         written there directly and never uploaded
object LogStorage {

    private const val KEY_SESSION_DEV_MODE = "session_dev_mode"
    private const val KEY_SESSION_STAMP = "session_stamp"

    fun beginSession(context: Context, startTimeMs: Long) {
        val stamp = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.getDefault()).format(Date(startTimeMs))
        prefs(context).edit()
            .putBoolean(KEY_SESSION_DEV_MODE, MainActivity.isDevMode(context))
            .putString(KEY_SESSION_STAMP, stamp)
            .apply()
    }

    // Mode of the session being logged (or last logged) — not the current toggle.
    fun isDevSession(context: Context): Boolean =
        prefs(context).getBoolean(KEY_SESSION_DEV_MODE, true)

    fun devSessionFolder(context: Context): String =
        "${Environment.DIRECTORY_DOWNLOADS}/NetworkLogger/session_${prefs(context).getString(KEY_SESSION_STAMP, "unknown")}/"

    // Developer sessions only; production rows go to CloudSync instead.
    fun appendRow(context: Context, baseName: String, header: String, row: String) {
        val stamp = prefs(context).getString(KEY_SESSION_STAMP, "unknown")
        val fileName = "${baseName}_$stamp.csv"
        val relativePath = devSessionFolder(context)

        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val existingUri: Uri? = resolver.query(
            collection,
            arrayOf(MediaStore.Downloads._ID),
            "${MediaStore.Downloads.DISPLAY_NAME} = ? AND ${MediaStore.Downloads.RELATIVE_PATH} = ?" +
                    " AND ${MediaStore.Downloads.IS_PENDING} = 0",
            arrayOf(fileName, relativePath), null
        )?.use { cursor ->
            if (cursor.moveToFirst())
                ContentUris.withAppendedId(
                    collection,
                    cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID))
                )
            else null
        }

        if (existingUri != null && !headerMatches(resolver, existingUri, header)) {
            // Written by an app version with different columns (e.g. before band
            // logging). Appending would put rows under the wrong header, so move the
            // old file aside — it keeps its data but is no longer the live file.
            val stamp = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.getDefault()).format(Date())
            resolver.update(existingUri, ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, "${baseName}_old-format_$stamp.csv")
            }, null, null)
            Log.w("CSV", "Header changed; moved old $fileName aside")
            createCsvFile(resolver, collection, fileName, relativePath, header, row)
            return
        }

        if (existingUri != null) {
            val stream = resolver.openOutputStream(existingUri, "wa")
            if (stream != null) {
                stream.use { it.write(row.toByteArray()) }
                return
            }
            // Broken entry — delete and recreate
            Log.w("CSV", "Stream null, recreating $fileName")
            resolver.delete(existingUri, null, null)
        }
        createCsvFile(resolver, collection, fileName, relativePath, header, row)
    }

    // Checked once per file per process; reading the first line every 5 s would be wasteful.
    private val verifiedHeaders = mutableSetOf<Uri>()

    private fun headerMatches(resolver: ContentResolver, uri: Uri, header: String): Boolean {
        if (uri in verifiedHeaders) return true
        val firstLine = try {
            resolver.openInputStream(uri)?.bufferedReader()?.use { it.readLine() }
        } catch (e: Exception) {
            null
        }
        // Unreadable or empty: let the normal append/recreate path deal with it
        if (firstLine == null) return true
        val matches = firstLine.trim() == header.trim()
        if (matches) verifiedHeaders.add(uri)
        return matches
    }

    private fun createCsvFile(
        resolver: ContentResolver,
        collection: Uri,
        fileName: String,
        relativePath: String,
        header: String,
        firstRow: String
    ) {
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, fileName)
            put(MediaStore.Downloads.MIME_TYPE, "text/csv")
            put(MediaStore.Downloads.RELATIVE_PATH, relativePath)
        }
        val uri = resolver.insert(collection, values)
        if (uri != null) {
            resolver.openOutputStream(uri)?.use { it.write(header.toByteArray()); it.write(firstRow.toByteArray()) }
            Log.d("CSV", "Created new file: $relativePath$fileName")
        } else {
            Log.e("CSV", "Failed to insert $fileName into MediaStore")
        }
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(MainActivity.PREFS_NAME, Context.MODE_PRIVATE)
}
