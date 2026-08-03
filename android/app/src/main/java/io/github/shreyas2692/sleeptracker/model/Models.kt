package io.github.shreyas2692.sleeptracker.model

import java.util.Locale

data class SleepStages(
    val deep: Int,
    val rem: Int,
    val light: Int,
    val awake: Int,
) {
    val totalMinutes: Int get() = deep + rem + light + awake
    val asleepMinutes: Int get() = deep + rem + light
}

data class SleepRecord(
    val id: Int,
    val date: String,
    val bedtime: String,
    val wake: String,
    val quality: Int,
    val notes: String,
    val hours: Double,
    val source: String,
    val stages: SleepStages?,
    val efficiency: Double?,
) {
    val sourceLabel: String?
        get() = when (source) {
            "manual" -> null
            "apple_health" -> "Apple Health"
            "fitbit" -> "Fitbit"
            else -> source.takeIf(String::isNotBlank)
        }
}

data class StatsDay(val date: String, val hours: Double?, val quality: Double?)
data class DebtDay(val date: String, val debtHours: Double, val cumulativeDebtHours: Double)
data class SleepDebt(val need: Double, val rolling14d: List<DebtDay>, val totalDebtHours: Double)

data class Stats(
    val total: Int,
    val avgHours: Double?,
    val avgQuality: Double?,
    val currentStreak: Int,
    val bestStreak: Int,
    val series: List<StatsDay>,
    val sleepDebt: SleepDebt?,
)

enum class SeriesRange(val apiValue: String, val label: String) {
    DAYS_30("30d", "30d"),
    DAYS_90("90d", "90d"),
    YEAR("1y", "1y"),
    ALL("all", "All"),
}

data class SeriesNight(
    val date: String,
    val hours: Double,
    val quality: Int?,
    val stages: SleepStages?,
    val source: String?,
)

data class SeriesResponse(
    val range: String,
    val nights: List<SeriesNight>,
    val start: String?,
    val end: String?,
)

data class WeeklyAverage(
    val label: String,
    val avgHours: Double,
    val avgQuality: Double,
    val count: Int,
)

data class DayOfWeekStat(
    val day: String,
    val avgHours: Double,
    val avgQuality: Double,
    val count: Int,
)

data class MonthlyTrendPoint(
    val label: String,
    val avgHours: Double,
    val count: Int,
)

data class BestWorstNights(
    val best: List<SleepRecord>,
    val worst: List<SleepRecord>,
)

data class Insights(
    val streak: Int,
    val consistency: Int,
    val weekly: List<WeeklyAverage>,
    val dayOfWeek: List<DayOfWeekStat>,
    val bestWorst: BestWorstNights,
    val monthly: List<MonthlyTrendPoint>,
)

data class AiSummaryResponse(
    val available: Boolean,
    val summary: String?,
    val reason: String?,
    val cached: Boolean,
)

data class NightDraft(
    val date: String,
    val bedtime: String,
    val wake: String,
    val quality: Int,
    val notes: String,
)

enum class WearableSource(val apiValue: String) {
    APPLE_HEALTH("apple_health"),
    FITBIT("fitbit"),
}

data class IngestNight(
    val date: String,
    val bedtime: String,
    val wake: String,
    val source: WearableSource,
    val quality: Int? = null,
    val notes: String = "",
    val stages: SleepStages? = null,
    val efficiency: Double? = null,
)

data class ServerConfig(
    val baseUrl: String = "",
    val username: String = "sleep",
    val password: String = "",
) {
    val normalizedBaseUrl: String get() = baseUrl.trim().trimEnd('/')
}

fun formatHours(value: Double?): String =
    value?.let { String.format(Locale.US, "%.1f", it) } ?: "--"

fun debtHeadline(value: Double): String = when {
    value > 0.05 -> "${formatHours(value)}h behind"
    value < -0.05 -> "Rested +${formatHours(-value)}h"
    else -> "On balance"
}

fun formatMinutes(value: Int): String {
    val hours = value / 60
    val minutes = value % 60
    return when {
        hours > 0 && minutes > 0 -> "${hours}h ${minutes}m"
        hours > 0 -> "${hours}h"
        else -> "${minutes}m"
    }
}
