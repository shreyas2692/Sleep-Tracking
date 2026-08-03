package io.github.shreyas2692.sleeptracker.network

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiJsonTest {
    @Test
    fun insightsPayloadParsesHeadlineNumbersAndSections() {
        val json = JSONObject(
            """
            {
              "stats": {"total": 12},
              "streak": 4,
              "consistency": 82,
              "weekly": [
                {"label": "Jul 20", "avg_hours": 7.4, "avg_quality": 3.8, "count": 6},
                {"label": "This week", "avg_hours": 0, "avg_quality": 0, "count": 0}
              ],
              "day_of_week": [
                {"day": "Mon", "avg_hours": 7.1, "avg_quality": 3.5, "count": 4}
              ],
              "best_worst": {
                "best": [
                  {"id": 3, "date": "2026-07-10", "bedtime": "22:30", "wake": "07:30",
                   "quality": 5, "notes": "", "hours": 9.0, "source": "manual",
                   "stages": null, "efficiency": null}
                ],
                "worst": []
              },
              "monthly": [
                {"label": "Jul 2026", "avg_hours": 7.2, "count": 20}
              ]
            }
            """.trimIndent(),
        )

        val insights = ApiJson.insights(json)

        assertEquals(4, insights.streak)
        assertEquals(82, insights.consistency)
        assertEquals(2, insights.weekly.size)
        assertEquals("Jul 20", insights.weekly[0].label)
        assertEquals(7.4, insights.weekly[0].avgHours, 1e-9)
        assertEquals(0, insights.weekly[1].count)
        assertEquals("Mon", insights.dayOfWeek[0].day)
        assertEquals(1, insights.bestWorst.best.size)
        assertEquals(9.0, insights.bestWorst.best[0].hours, 1e-9)
        assertNull(insights.bestWorst.best[0].stages)
        assertTrue(insights.bestWorst.worst.isEmpty())
        assertEquals("Jul 2026", insights.monthly[0].label)
    }

    @Test
    fun summaryHiddenWhenUnavailable() {
        val unavailable = ApiJson.summary(JSONObject("""{"available": false, "reason": "no_api_key"}"""))
        assertFalse(unavailable.available)
        assertEquals("no_api_key", unavailable.reason)
        assertNull(unavailable.summary)

        val available = ApiJson.summary(
            JSONObject("""{"available": true, "summary": "Slept well.", "generated_at": "2026-08-01", "cached": true}"""),
        )
        assertTrue(available.available)
        assertEquals("Slept well.", available.summary)
        assertTrue(available.cached)
    }

    @Test
    fun recordParsesStagesAndEfficiency(): Unit {
        val record = ApiJson.record(
            JSONObject(
                """
                {"id": 7, "date": "2026-07-29", "bedtime": "23:00", "wake": "07:00",
                 "quality": 4, "notes": "n", "hours": 8.0, "source": "fitbit",
                 "stages": {"deep": 80, "rem": 100, "light": 260, "awake": 40},
                 "efficiency": 91.7}
                """.trimIndent(),
            ),
        )
        assertEquals("fitbit", record.source)
        val stages = record.stages!!
        assertEquals(80, stages.deep)
        assertEquals(480, stages.totalMinutes)
        assertEquals(91.7, record.efficiency!!, 1e-9)
    }
}
