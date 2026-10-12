package com.example.networklogger

import org.junit.Assert.assertEquals
import org.junit.Test

class BandInfoTest {

    @Test
    fun lteChannelsMapToTheirBand() {
        assertEquals(listOf(3), BandInfo.lteBandsForEarfcn(1850))    // 1800 MHz, common in India
        assertEquals(listOf(40), BandInfo.lteBandsForEarfcn(39150))  // 2300 MHz TDD
        assertEquals(listOf(5), BandInfo.lteBandsForEarfcn(2500))    // 850 MHz
        assertEquals(listOf(1), BandInfo.lteBandsForEarfcn(0))       // range edges are inclusive
        assertEquals(listOf(3), BandInfo.lteBandsForEarfcn(1949))
    }

    @Test
    fun lteChannelOutsideAnyBandIsEmpty() {
        assertEquals(emptyList<Int>(), BandInfo.lteBandsForEarfcn(2700))  // gap between B5 and B7
    }

    @Test
    fun nrChannelsMapToTheirBand() {
        assertEquals(listOf(28), BandInfo.nrBandsForArfcn(152000))   // 700 MHz
        assertEquals(listOf(79), BandInfo.nrBandsForArfcn(700000))
    }

    @Test
    fun overlappingNrBandsListNarrowestFirst() {
        // 3.5 GHz: n78 sits inside n77, so both are candidates and n78 leads
        assertEquals(listOf(78, 77), BandInfo.nrBandsForArfcn(636666))
        // Above n78's top edge only n77 remains
        assertEquals(listOf(77), BandInfo.nrBandsForArfcn(660000))
        // n1 sits inside n66
        assertEquals(listOf(1, 66), BandInfo.nrBandsForArfcn(428000))
    }
}
