package io.github.shreyas2692.sleeptracker.network

import io.github.shreyas2692.sleeptracker.model.DebtDay
import io.github.shreyas2692.sleeptracker.model.AiSummaryResponse
import io.github.shreyas2692.sleeptracker.model.BestWorstNights
import io.github.shreyas2692.sleeptracker.model.DayOfWeekStat
import io.github.shreyas2692.sleeptracker.model.IngestNight
import io.github.shreyas2692.sleeptracker.model.Insights
import io.github.shreyas2692.sleeptracker.model.MonthlyTrendPoint
import io.github.shreyas2692.sleeptracker.model.WeeklyAverage
import io.github.shreyas2692.sleeptracker.model.NightDraft
import io.github.shreyas2692.sleeptracker.model.SeriesNight
import io.github.shreyas2692.sleeptracker.model.SeriesRange
import io.github.shreyas2692.sleeptracker.model.SeriesResponse
import io.github.shreyas2692.sleeptracker.model.ServerConfig
import io.github.shreyas2692.sleeptracker.model.SleepDebt
import io.github.shreyas2692.sleeptracker.model.SleepRecord
import io.github.shreyas2692.sleeptracker.model.SleepStages
import io.github.shreyas2692.sleeptracker.model.Stats
import io.github.shreyas2692.sleeptracker.model.StatsDay
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.Inet6Address
import java.net.InetAddress
import java.net.URI
import java.net.URLEncoder
import java.net.URL
import java.nio.charset.StandardCharsets
import java.util.Base64

data class RequestSpec(
    val method: String,
    val url: String,
    val headers: Map<String, String>,
    val body: ByteArray? = null,
    val additionalSuccessStatuses: Set<Int> = emptySet(),
)

class ApiException(val status: Int?, message: String) : IOException(message)

object ServerUrlPolicy {
    fun validate(url: String, allowInsecureLocal: Boolean): String? {
        val normalized = url.trim().trimEnd('/')
        val uri = try {
            URI(normalized)
        } catch (_: Exception) {
            return "Enter a valid server URL."
        }
        if (uri.host.isNullOrBlank() || uri.userInfo != null || uri.query != null || uri.fragment != null) {
            return "Enter a server origin without credentials, a query, or a fragment."
        }
        if (uri.path !in listOf("", "/")) return "The server URL must not include a path."
        val scheme = uri.scheme?.lowercase()
        if (scheme == "https") return null
        if (scheme == "http" && allowInsecureLocal && isLocalHost(uri.host)) return null
        return if (allowInsecureLocal) {
            "Use HTTPS, or a loopback/private-LAN HTTP address in a debug build."
        } else {
            "Release builds require HTTPS."
        }
    }

    internal fun isLocalHost(host: String): Boolean {
        val value = host.trim('[', ']').lowercase()
        if (value == "localhost" || value.endsWith(".local") || value == "::1") return true
        if (':' in value) {
            val address = runCatching { InetAddress.getByName(value) }.getOrNull() as? Inet6Address
                ?: return false
            val first = address.address[0].toInt() and 0xff
            val second = address.address[1].toInt() and 0xff
            return first == 0xfc || first == 0xfd || (first == 0xfe && second in 0x80..0xbf)
        }
        val parts = value.split('.')
        if (parts.size != 4) return false
        val octets = parts.map { it.toIntOrNull() ?: return false }
        if (octets.any { it !in 0..255 }) return false
        return octets[0] == 127 || octets[0] == 10 ||
            (octets[0] == 192 && octets[1] == 168) ||
            (octets[0] == 172 && octets[1] in 16..31)
    }
}

class RequestFactory(private val config: ServerConfig) {
    fun health(): RequestSpec = request("GET", "/healthz", authorize = false)
    fun stats(): RequestSpec = request("GET", "/api/stats")
    fun records(): RequestSpec = request("GET", "/api/records?limit=10000")
    fun series(range: SeriesRange): RequestSpec = request("GET", "/api/series?range=${range.apiValue}")
    fun summary(): RequestSpec = request("GET", "/api/summary")
    fun insights(): RequestSpec = request("GET", "/api/insights")

    fun add(draft: NightDraft): RequestSpec = form("/add", draft.items())
    fun edit(id: Int, draft: NightDraft): RequestSpec = form("/edit/$id", draft.items())
    fun delete(id: Int): RequestSpec = form("/delete/$id", emptyList())
    fun updateSettings(sleepGoal: String, bedtimeGoal: String): RequestSpec = formRedirect(
        "/settings/update",
        listOf("sleep_goal" to sleepGoal, "bedtime_goal" to bedtimeGoal),
    )
    fun clear(): RequestSpec = formRedirect("/settings/clear", emptyList())

    fun ingest(nights: List<IngestNight>): RequestSpec {
        val payload = JSONArray()
        nights.forEach { night ->
            payload.put(
                JSONObject()
                    .put("date", night.date)
                    .put("bedtime", night.bedtime)
                    .put("wake", night.wake)
                    .put("source", night.source.apiValue)
                    .put("notes", night.notes)
                    .putNullable("quality", night.quality)
                    .putNullable("efficiency", night.efficiency)
                    .putNullable(
                        "stages",
                        night.stages?.let {
                            JSONObject()
                                .put("deep", it.deep)
                                .put("rem", it.rem)
                                .put("light", it.light)
                                .put("awake", it.awake)
                        },
                    ),
            )
        }
        return request(
            method = "POST",
            path = "/api/ingest",
            body = payload.toString().toByteArray(StandardCharsets.UTF_8),
            contentType = "application/json; charset=utf-8",
        )
    }

    private fun NightDraft.items() = listOf(
        "date" to date,
        "bedtime" to bedtime,
        "wake" to wake,
        "quality" to quality.toString(),
        "notes" to notes,
    )

    private fun form(path: String, items: List<Pair<String, String>>): RequestSpec = request(
        method = "POST",
        path = path,
        body = encodeForm(items).toByteArray(StandardCharsets.UTF_8),
        contentType = "application/x-www-form-urlencoded; charset=utf-8",
        ajax = true,
    )

    private fun formRedirect(path: String, items: List<Pair<String, String>>): RequestSpec = request(
        method = "POST",
        path = path,
        body = encodeForm(items).toByteArray(StandardCharsets.UTF_8),
        contentType = "application/x-www-form-urlencoded; charset=utf-8",
        additionalSuccessStatuses = setOf(302, 303),
    )

    private fun request(
        method: String,
        path: String,
        authorize: Boolean = true,
        body: ByteArray? = null,
        contentType: String? = null,
        ajax: Boolean = false,
        additionalSuccessStatuses: Set<Int> = emptySet(),
    ): RequestSpec {
        val headers = mutableMapOf("Accept" to "application/json")
        if (contentType != null) headers["Content-Type"] = contentType
        if (ajax) headers["X-Requested-With"] = "XMLHttpRequest"
        if (authorize && (config.username.isNotEmpty() || config.password.isNotEmpty())) {
            val raw = "${config.username}:${config.password}".toByteArray(StandardCharsets.UTF_8)
            headers["Authorization"] = "Basic ${Base64.getEncoder().encodeToString(raw)}"
        }
        return RequestSpec(
            method,
            config.normalizedBaseUrl + path,
            headers,
            body,
            additionalSuccessStatuses,
        )
    }

    companion object {
        fun encodeForm(items: List<Pair<String, String>>): String = items.joinToString("&") { (key, value) ->
            "${encode(key)}=${encode(value)}"
        }

        private fun encode(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.name())
    }
}

class ApiClient(private val config: ServerConfig) {
    private val requests = RequestFactory(config)

    fun testConnection(): Stats {
        val health = JSONObject(execute(requests.health()))
        if (!health.optBoolean("ok")) throw ApiException(503, "Server database is not ready.")
        return getStats()
    }

    fun getStats(): Stats = ApiJson.stats(JSONObject(execute(requests.stats())))
    fun getRecords(): List<SleepRecord> = ApiJson.records(JSONArray(execute(requests.records())))
    fun getSeries(range: SeriesRange): SeriesResponse = ApiJson.series(JSONObject(execute(requests.series(range))))
    fun getSummary(): AiSummaryResponse = ApiJson.summary(JSONObject(execute(requests.summary())))
    fun getInsights(): Insights = ApiJson.insights(JSONObject(execute(requests.insights())))

    fun add(draft: NightDraft) { execute(requests.add(draft)) }
    fun edit(id: Int, draft: NightDraft) { execute(requests.edit(id, draft)) }
    fun delete(id: Int) { execute(requests.delete(id)) }
    fun updateSettings(sleepGoal: String, bedtimeGoal: String) {
        execute(requests.updateSettings(sleepGoal, bedtimeGoal))
    }
    fun clear() { execute(requests.clear()) }
    fun ingest(nights: List<IngestNight>) { execute(requests.ingest(nights)) }

    private fun execute(spec: RequestSpec): String {
        val connection = URL(spec.url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = spec.method
            connection.connectTimeout = 90_000
            connection.readTimeout = 120_000
            // Never forward Basic credentials across an automatic redirect.
            connection.instanceFollowRedirects = false
            spec.headers.forEach(connection::setRequestProperty)
            spec.body?.let {
                connection.doOutput = true
                connection.outputStream.use { output -> output.write(it) }
            }
            val status = connection.responseCode
            val success = status in 200..299 || status in spec.additionalSuccessStatuses
            val stream = if (success) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (!success) {
                val serverMessage = runCatching { JSONObject(response).optString("error") }.getOrNull()
                val message = when (status) {
                    401 -> "Authentication failed. Check the username and password."
                    else -> serverMessage?.takeIf(String::isNotBlank) ?: "Server request failed ($status)."
                }
                throw ApiException(status, message)
            }
            return response
        } catch (error: ApiException) {
            throw error
        } catch (error: IOException) {
            throw ApiException(null, error.message ?: "Could not reach the server.")
        } finally {
            connection.disconnect()
        }
    }
}

object ApiJson {
    fun records(array: JSONArray): List<SleepRecord> = buildList {
        for (index in 0 until array.length()) add(record(array.getJSONObject(index)))
    }

    fun record(json: JSONObject) = SleepRecord(
        id = json.getInt("id"),
        date = json.getString("date"),
        bedtime = json.getString("bedtime"),
        wake = json.getString("wake"),
        quality = json.getInt("quality"),
        notes = json.optString("notes", ""),
        hours = json.getDouble("hours"),
        source = json.optString("source", "manual"),
        stages = json.objectOrNull("stages")?.let(::stages),
        efficiency = json.doubleOrNull("efficiency"),
    )

    fun stats(json: JSONObject) = Stats(
        total = json.getInt("total"),
        avgHours = json.doubleOrNull("avg_hours"),
        avgQuality = json.doubleOrNull("avg_quality"),
        currentStreak = json.getInt("current_streak"),
        bestStreak = json.getInt("best_streak"),
        series = json.getJSONArray("series").objects().map {
            StatsDay(it.getString("date"), it.doubleOrNull("hours"), it.doubleOrNull("quality"))
        },
        sleepDebt = json.objectOrNull("sleep_debt")?.let { debt ->
            SleepDebt(
                need = debt.getDouble("need"),
                rolling14d = debt.getJSONArray("rolling_14d").objects().map {
                    DebtDay(it.getString("date"), it.getDouble("debt_hours"), it.getDouble("cumulative_debt_hours"))
                },
                totalDebtHours = debt.getDouble("total_debt_hours"),
            )
        },
    )

    fun series(json: JSONObject) = SeriesResponse(
        range = json.getString("range"),
        nights = json.getJSONArray("nights").objects().map {
            SeriesNight(
                date = it.getString("date"),
                hours = it.getDouble("hours"),
                quality = it.intOrNull("quality"),
                stages = it.objectOrNull("stages")?.let(::stages),
                source = it.stringOrNull("source"),
            )
        },
        start = json.stringOrNull("start"),
        end = json.stringOrNull("end"),
    )

    fun insights(json: JSONObject) = Insights(
        streak = json.optInt("streak", 0),
        consistency = json.optInt("consistency", 0),
        weekly = json.getJSONArray("weekly").objects().map {
            WeeklyAverage(
                label = it.getString("label"),
                avgHours = it.getDouble("avg_hours"),
                avgQuality = it.getDouble("avg_quality"),
                count = it.getInt("count"),
            )
        },
        dayOfWeek = json.getJSONArray("day_of_week").objects().map {
            DayOfWeekStat(
                day = it.getString("day"),
                avgHours = it.getDouble("avg_hours"),
                avgQuality = it.getDouble("avg_quality"),
                count = it.getInt("count"),
            )
        },
        bestWorst = json.getJSONObject("best_worst").let { pair ->
            BestWorstNights(
                best = records(pair.getJSONArray("best")),
                worst = records(pair.getJSONArray("worst")),
            )
        },
        monthly = json.getJSONArray("monthly").objects().map {
            MonthlyTrendPoint(
                label = it.getString("label"),
                avgHours = it.getDouble("avg_hours"),
                count = it.getInt("count"),
            )
        },
    )

    fun summary(json: JSONObject) = AiSummaryResponse(
        available = json.optBoolean("available", false),
        summary = json.stringOrNull("summary"),
        reason = json.stringOrNull("reason"),
        cached = json.optBoolean("cached", false),
    )

    private fun stages(json: JSONObject) = SleepStages(
        deep = json.getInt("deep"),
        rem = json.getInt("rem"),
        light = json.getInt("light"),
        awake = json.getInt("awake"),
    )

    private fun JSONArray.objects(): List<JSONObject> =
        (0 until length()).map(::getJSONObject)

    private fun JSONObject.objectOrNull(key: String): JSONObject? =
        if (!has(key) || isNull(key)) null else getJSONObject(key)
    private fun JSONObject.doubleOrNull(key: String): Double? =
        if (!has(key) || isNull(key)) null else getDouble(key)
    private fun JSONObject.intOrNull(key: String): Int? =
        if (!has(key) || isNull(key)) null else getInt(key)
    private fun JSONObject.stringOrNull(key: String): String? =
        if (!has(key) || isNull(key)) null else getString(key)
}

private fun JSONObject.putNullable(key: String, value: Any?): JSONObject = put(key, value ?: JSONObject.NULL)
