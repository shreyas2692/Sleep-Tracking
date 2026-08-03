package io.github.shreyas2692.sleeptracker.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.shreyas2692.sleeptracker.BuildConfig
import io.github.shreyas2692.sleeptracker.data.AndroidConfigPersistence
import io.github.shreyas2692.sleeptracker.data.ConfigRepository
import io.github.shreyas2692.sleeptracker.model.Insights
import io.github.shreyas2692.sleeptracker.model.NightDraft
import io.github.shreyas2692.sleeptracker.model.SeriesRange
import io.github.shreyas2692.sleeptracker.model.SeriesResponse
import io.github.shreyas2692.sleeptracker.model.ServerConfig
import io.github.shreyas2692.sleeptracker.model.SleepRecord
import io.github.shreyas2692.sleeptracker.model.Stats
import io.github.shreyas2692.sleeptracker.network.ApiClient
import io.github.shreyas2692.sleeptracker.network.ServerUrlPolicy
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class DataStatus { NEEDS_CONFIGURATION, LOADING, READY, EMPTY, ERROR }
enum class BusyAction { REFRESH, SAVE_NIGHT, DELETE_NIGHT, SAVE_SETTINGS, CLEAR_DATA }

data class Snapshot(
    val records: List<SleepRecord>,
    val stats: Stats,
    val series: SeriesResponse,
)

data class AppUiState(
    val config: ServerConfig = ServerConfig(),
    val status: DataStatus = DataStatus.NEEDS_CONFIGURATION,
    val records: List<SleepRecord> = emptyList(),
    val stats: Stats? = null,
    val selectedRange: SeriesRange = SeriesRange.DAYS_30,
    val seriesByRange: Map<SeriesRange, SeriesResponse> = emptyMap(),
    val seriesLoading: Boolean = false,
    val seriesError: String? = null,
    val insights: Insights? = null,
    val insightsLoading: Boolean = false,
    val insightsError: String? = null,
    val aiSummary: String? = null,
    val summaryLoading: Boolean = false,
    val summaryMessage: String? = null,
    val busyAction: BusyAction? = null,
    val completedAction: BusyAction? = null,
    val error: String? = null,
    val message: String? = null,
    val connectionResult: String? = null,
    val testingConnection: Boolean = false,
)

object StoreReducer {
    fun refreshed(state: AppUiState, snapshot: Snapshot): AppUiState = state.copy(
        status = if (snapshot.records.isEmpty()) DataStatus.EMPTY else DataStatus.READY,
        records = snapshot.records,
        stats = snapshot.stats,
        selectedRange = SeriesRange.DAYS_30,
        seriesByRange = mapOf(SeriesRange.DAYS_30 to snapshot.series),
        seriesLoading = false,
        seriesError = null,
        insights = null,
        insightsLoading = false,
        insightsError = null,
        aiSummary = null,
        summaryLoading = false,
        summaryMessage = null,
        busyAction = null,
        completedAction = null,
        error = null,
    )

    fun failed(state: AppUiState, message: String): AppUiState = state.copy(
        status = if (state.stats == null && state.records.isEmpty()) DataStatus.ERROR else state.status,
        busyAction = null,
        error = message,
    )
}

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val repository = ConfigRepository(AndroidConfigPersistence(application))
    private val _state = MutableStateFlow(AppUiState(config = repository.load()))
    val state: StateFlow<AppUiState> = _state.asStateFlow()
    private var refreshGeneration = 0
    private var seriesGeneration = 0
    private var connectionGeneration = 0

    init {
        val config = _state.value.config
        if (validateConfig(config) == null) refresh() else {
            _state.value = _state.value.copy(status = DataStatus.NEEDS_CONFIGURATION)
        }
    }

    fun validateConfig(config: ServerConfig): String? =
        ServerUrlPolicy.validate(config.normalizedBaseUrl, BuildConfig.DEBUG)

    fun saveConfig(config: ServerConfig) {
        val normalized = config.copy(
            baseUrl = config.normalizedBaseUrl,
            username = config.username.trim(),
        )
        val error = validateConfig(normalized)
        if (error != null) {
            _state.value = _state.value.copy(connectionResult = error)
            return
        }
        runCatching { repository.save(normalized) }
            .onFailure {
                _state.value = _state.value.copy(connectionResult = "Could not save credentials securely.")
                return
            }
        refreshGeneration++
        seriesGeneration++
        connectionGeneration++
        _state.value = AppUiState(
            config = normalized,
            status = DataStatus.LOADING,
            connectionResult = "Configuration saved.",
        )
        refresh()
    }

    fun testConnection(config: ServerConfig) {
        val normalized = config.copy(baseUrl = config.normalizedBaseUrl, username = config.username.trim())
        validateConfig(normalized)?.let {
            _state.value = _state.value.copy(connectionResult = it)
            return
        }
        _state.value = _state.value.copy(testingConnection = true, connectionResult = null)
        val generation = ++connectionGeneration
        viewModelScope.launch {
            val result = runCatching { withContext(Dispatchers.IO) { ApiClient(normalized).testConnection() } }
            if (generation != connectionGeneration) return@launch
            _state.value = _state.value.copy(
                testingConnection = false,
                connectionResult = result.fold(
                    onSuccess = { "Connected. ${it.total} nights are available." },
                    onFailure = { it.userMessage() },
                ),
            )
        }
    }

    fun refresh() {
        val config = _state.value.config
        if (validateConfig(config) != null) {
            _state.value = _state.value.copy(status = DataStatus.NEEDS_CONFIGURATION)
            return
        }
        val generation = ++refreshGeneration
        seriesGeneration++
        _state.value = _state.value.copy(
            status = if (_state.value.stats == null) DataStatus.LOADING else _state.value.status,
            busyAction = BusyAction.REFRESH,
            error = null,
        )
        viewModelScope.launch {
            val result = runCatching { withContext(Dispatchers.IO) { fetchSnapshot(ApiClient(config)) } }
            if (generation != refreshGeneration) return@launch
            _state.value = result.fold(
                onSuccess = { StoreReducer.refreshed(_state.value, it) },
                onFailure = { StoreReducer.failed(_state.value, it.userMessage()) },
            )
        }
    }

    fun selectRange(range: SeriesRange) {
        val generation = ++seriesGeneration
        val config = _state.value.config
        _state.value = _state.value.copy(
            selectedRange = range,
            seriesError = null,
            seriesLoading = _state.value.seriesByRange[range] == null,
        )
        if (_state.value.seriesByRange[range] != null) return
        _state.value = _state.value.copy(seriesLoading = true)
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) { ApiClient(config).getSeries(range) }
            }
            if (generation != seriesGeneration || config != _state.value.config) return@launch
            _state.value = result.fold(
                onSuccess = {
                    _state.value.copy(
                        seriesByRange = _state.value.seriesByRange + (range to it),
                        seriesLoading = false,
                        seriesError = null,
                    )
                },
                onFailure = {
                    _state.value.copy(seriesLoading = false, seriesError = it.userMessage())
                },
            )
        }
    }

    fun addNight(draft: NightDraft) = mutate(BusyAction.SAVE_NIGHT, "Night added.") { add(draft) }
    fun editNight(id: Int, draft: NightDraft) = mutate(BusyAction.SAVE_NIGHT, "Night updated.") { edit(id, draft) }
    fun deleteNight(id: Int) = mutate(BusyAction.DELETE_NIGHT, "Night deleted.") { delete(id) }

    fun saveGoals(sleepGoal: String, bedtimeGoal: String) =
        mutate(BusyAction.SAVE_SETTINGS, "Settings saved.") { updateSettings(sleepGoal, bedtimeGoal) }

    fun clearAll() = mutate(BusyAction.CLEAR_DATA, "All server records cleared.") { clear() }

    fun loadInsights(force: Boolean = false) {
        val current = _state.value
        if (current.insightsLoading || (!force && current.insights != null)) return
        val config = current.config
        val generation = refreshGeneration
        _state.value = current.copy(insightsLoading = true, insightsError = null)
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) { ApiClient(config).getInsights() }
            }
            if (generation != refreshGeneration || config != _state.value.config) return@launch
            _state.value = result.fold(
                onSuccess = {
                    _state.value.copy(insights = it, insightsLoading = false, insightsError = null)
                },
                onFailure = {
                    _state.value.copy(insightsLoading = false, insightsError = it.userMessage())
                },
            )
        }
    }

    fun requestSummary() {
        if (_state.value.summaryLoading || _state.value.busyAction != null) return
        val config = _state.value.config
        val generation = refreshGeneration
        _state.value = _state.value.copy(
            summaryLoading = true,
            aiSummary = null,
            summaryMessage = null,
        )
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) { ApiClient(config).getSummary() }
            }
            if (generation != refreshGeneration || config != _state.value.config) return@launch
            val response = result.getOrNull()
            _state.value = _state.value.copy(
                aiSummary = response?.takeIf { it.available }?.summary,
                summaryLoading = false,
                summaryMessage = when {
                    result.isFailure -> result.exceptionOrNull()?.userMessage()
                        ?: "The AI summary request failed."
                    response?.available == false -> "AI summaries are not enabled on this server."
                    response?.reason == "not_enough_data" -> "At least 7 nights are needed for a weekly summary."
                    response?.summary.isNullOrBlank() -> "No weekly summary is available."
                    else -> null
                },
            )
        }
    }

    fun dismissNotice() {
        _state.value = _state.value.copy(error = null, message = null, connectionResult = null)
    }

    fun consumeCompletedAction() {
        _state.value = _state.value.copy(completedAction = null)
    }

    private fun mutate(action: BusyAction, successMessage: String, block: ApiClient.() -> Unit) {
        if (_state.value.busyAction != null) return
        val config = _state.value.config
        val generation = ++refreshGeneration
        seriesGeneration++
        _state.value = _state.value.copy(busyAction = action, completedAction = null, error = null)
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val client = ApiClient(config)
                    client.block()
                    fetchSnapshot(client)
                }
            }
            if (generation != refreshGeneration || config != _state.value.config) return@launch
            _state.value = result.fold(
                onSuccess = {
                    StoreReducer.refreshed(_state.value, it).copy(
                        message = successMessage,
                        completedAction = action,
                    )
                },
                onFailure = { StoreReducer.failed(_state.value, it.userMessage()) },
            )
        }
    }

    private fun fetchSnapshot(client: ApiClient) = Snapshot(
        records = client.getRecords(),
        stats = client.getStats(),
        series = client.getSeries(SeriesRange.DAYS_30),
    )

    private fun Throwable.userMessage(): String = message?.takeIf(String::isNotBlank)
        ?: "The server request failed."
}
