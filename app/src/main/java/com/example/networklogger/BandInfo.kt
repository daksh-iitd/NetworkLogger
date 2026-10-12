// BandInfo.kt

package com.example.networklogger

import android.os.Build
import android.telephony.CellIdentityLte
import android.telephony.CellIdentityNr

// Operating band of a cell, e.g. "B3" (LTE) or "n78" (NR).
//
// Android 11+ can report the band directly (CellIdentity*.getBands()), but some
// devices return an empty array, so we fall back to mapping the channel number
// (EARFCN / NR-ARFCN) through the 3GPP downlink tables. Some NR bands share
// channel ranges (n77 ⊃ n78, n1 ⊂ n66, …); in that case every candidate is
// returned, narrowest band first, rather than guessing — e.g. "n78/n77".
data class BandInfo(
    val arfcn: Int?,
    val band: String,
    // "reported" = from getBands(), "arfcn" = derived from the channel number
    val source: String,
    val bandwidthMhz: Double?,
) {
    companion object {
        val UNKNOWN = BandInfo(null, "N/A", "N/A", null)

        fun of(identity: CellIdentityLte): BandInfo {
            val earfcn = identity.earfcn.takeIf { it != Int.MAX_VALUE && it >= 0 }
            val bandwidth = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
                identity.bandwidth.takeIf { it != Int.MAX_VALUE && it > 0 }?.let { it / 1000.0 }
            else null

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val reported = identity.bands
                if (reported.isNotEmpty()) {
                    return BandInfo(earfcn, reported.joinToString("/") { "B$it" }, "reported", bandwidth)
                }
            }
            val derived = earfcn?.let { lteBandsForEarfcn(it) }.orEmpty()
            return if (derived.isEmpty()) BandInfo(earfcn, "N/A", "N/A", bandwidth)
            else BandInfo(earfcn, derived.joinToString("/") { "B$it" }, "arfcn", bandwidth)
        }

        fun of(identity: CellIdentityNr): BandInfo {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return UNKNOWN
            val nrarfcn = identity.nrarfcn.takeIf { it != Int.MAX_VALUE && it >= 0 }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val reported = identity.bands
                if (reported.isNotEmpty()) {
                    return BandInfo(nrarfcn, reported.joinToString("/") { "n$it" }, "reported", null)
                }
            }
            val derived = nrarfcn?.let { nrBandsForArfcn(it) }.orEmpty()
            return if (derived.isEmpty()) BandInfo(nrarfcn, "N/A", "N/A", null)
            else BandInfo(nrarfcn, derived.joinToString("/") { "n$it" }, "arfcn", null)
        }

        // 3GPP TS 36.101 Table 5.7.3-1, downlink EARFCN ranges (band, first, last)
        private val LTE_DL = listOf(
            Triple(1, 0, 599), Triple(2, 600, 1199), Triple(3, 1200, 1949),
            Triple(4, 1950, 2399), Triple(5, 2400, 2649), Triple(7, 2750, 3449),
            Triple(8, 3450, 3799), Triple(12, 5010, 5179), Triple(13, 5180, 5279),
            Triple(14, 5280, 5379), Triple(17, 5730, 5849), Triple(18, 5850, 5999),
            Triple(19, 6000, 6149), Triple(20, 6150, 6449), Triple(25, 8040, 8689),
            Triple(26, 8690, 9039), Triple(28, 9210, 9659), Triple(29, 9660, 9769),
            Triple(30, 9770, 9869), Triple(32, 9920, 10359), Triple(38, 37750, 38249),
            Triple(39, 38250, 38649), Triple(40, 38650, 39649), Triple(41, 39650, 41589),
            Triple(42, 41590, 43589), Triple(43, 43590, 45589), Triple(46, 46790, 54539),
            Triple(48, 55240, 56739), Triple(66, 66436, 67335), Triple(71, 68586, 68935),
        )

        // 3GPP TS 38.104 Table 5.4.2.3-1, downlink NR-ARFCN ranges (band, first, last)
        private val NR_DL = listOf(
            Triple(1, 422000, 434000), Triple(3, 361000, 376000), Triple(5, 173800, 178800),
            Triple(7, 524000, 538000), Triple(8, 185000, 192000), Triple(20, 158200, 164200),
            Triple(28, 151600, 160600), Triple(38, 514000, 524000), Triple(40, 460000, 480000),
            Triple(41, 499200, 537999), Triple(66, 422000, 440000), Triple(71, 123400, 130400),
            Triple(77, 620000, 680000), Triple(78, 620000, 653333), Triple(79, 693334, 733333),
            Triple(257, 2054166, 2104165), Triple(258, 2016667, 2070832),
            Triple(260, 2229166, 2279165), Triple(261, 2070833, 2084999),
        )

        internal fun lteBandsForEarfcn(earfcn: Int) = matches(LTE_DL, earfcn)
        internal fun nrBandsForArfcn(arfcn: Int) = matches(NR_DL, arfcn)

        // Narrowest range first, so the most specific band leads ("n78/n77").
        private fun matches(table: List<Triple<Int, Int, Int>>, channel: Int): List<Int> =
            table.filter { channel in it.second..it.third }
                .sortedBy { it.third - it.second }
                .map { it.first }
    }
}
