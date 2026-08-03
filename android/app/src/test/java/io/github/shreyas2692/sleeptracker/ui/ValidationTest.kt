package io.github.shreyas2692.sleeptracker.ui

import io.github.shreyas2692.sleeptracker.model.NightDraft
import io.github.shreyas2692.sleeptracker.model.SeriesRange
import io.github.shreyas2692.sleeptracker.model.SeriesResponse
import io.github.shreyas2692.sleeptracker.model.SleepDebt
import io.github.shreyas2692.sleeptracker.model.SleepRecord
import io.github.shreyas2692.sleeptracker.model.Stats
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ValidationTest {
    @Test
    fun validNightPasses() {
        assertNull(validateNight(NightDraft("2026-07-30", "23:05", "07:10", 5, "fine")))
    }

    @Test
    fun nightValidationMatchesServerContract() {
        val valid = NightDraft("2026-07-30", "23:05", "07:10", 4, "")
        assertTrue(validateNight(valid.copy(date = "2026-7-30"))!!.contains("YYYY-MM-DD"))
        assertTrue(validateNight(valid.copy(bedtime = "7:00"))!!.contains("HH:MM"))
        assertTrue(validateNight(valid.copy(wake = "25:00"))!!.contains("HH:MM"))
        assertTrue(validateNight(valid.copy(quality = 0))!!.contains("Quality"))
        assertTrue(validateNight(valid.copy(notes = "x".repeat(501)))!!.contains("500"))
    }

    @Test
    fun futureDatesAreRejectedAndTodayIsAllowed() {
        val valid = NightDraft("2026-07-30", "23:05", "07:10", 4, "")
        val tomorrow = java.time.LocalDate.now().plusDays(1).toString()
        assertTrue(validateNight(valid.copy(date = tomorrow))!!.contains("future"))
        assertNull(validateNight(valid.copy(date = java.time.LocalDate.now().toString())))
    }

    @Test
    fun goalValidationMatchesServerContract() {
        assertNull(validateGoals("8.5", "23:15"))
        assertNull(validateGoals("", ""))
        assertTrue(validateGoals("0", "")!!.contains("between"))
        assertTrue(validateGoals("NaN", "")!!.contains("between"))
        assertTrue(validateGoals("8", "7:00")!!.contains("HH:MM"))
    }

    @Test
    fun refreshedStateInvalidatesEveryCachedTrendRange() {
        val old = AppUiState(
            selectedRange = SeriesRange.ALL,
            seriesLoading = true,
            seriesError = "stale",
            seriesByRange = mapOf(
                SeriesRange.DAYS_30 to SeriesResponse("30d", emptyList(), null, null),
                SeriesRange.ALL to SeriesResponse("all", emptyList(), null, null),
            ),
        )
        val record = SleepRecord(1, "2026-07-30", "23:00", "07:00", 4, "", 8.0, "manual", null, null)
        val stats = Stats(1, 8.0, 4.0, 1, 1, emptyList(), SleepDebt(8.0, emptyList(), 0.0))
        val freshSeries = SeriesResponse("30d", emptyList(), "2026-07-02", "2026-07-31")

        val refreshed = StoreReducer.refreshed(old, Snapshot(listOf(record), stats, freshSeries))

        assertEquals(setOf(SeriesRange.DAYS_30), refreshed.seriesByRange.keys)
        assertEquals(SeriesRange.DAYS_30, refreshed.selectedRange)
        assertEquals(false, refreshed.seriesLoading)
        assertNull(refreshed.seriesError)
        assertEquals(DataStatus.READY, refreshed.status)
        assertEquals(listOf(record), refreshed.records)
    }
}
