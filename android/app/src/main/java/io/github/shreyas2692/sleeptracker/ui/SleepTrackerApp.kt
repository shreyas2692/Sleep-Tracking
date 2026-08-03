package io.github.shreyas2692.sleeptracker.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.shreyas2692.sleeptracker.BuildConfig
import io.github.shreyas2692.sleeptracker.model.NightDraft
import io.github.shreyas2692.sleeptracker.model.SeriesNight
import io.github.shreyas2692.sleeptracker.model.SeriesRange
import io.github.shreyas2692.sleeptracker.model.ServerConfig
import io.github.shreyas2692.sleeptracker.model.SleepRecord
import io.github.shreyas2692.sleeptracker.model.SleepStages
import io.github.shreyas2692.sleeptracker.model.WeeklyAverage
import io.github.shreyas2692.sleeptracker.model.debtHeadline
import io.github.shreyas2692.sleeptracker.model.formatHours
import io.github.shreyas2692.sleeptracker.model.formatMinutes
import io.github.shreyas2692.sleeptracker.ui.theme.StageAwake
import io.github.shreyas2692.sleeptracker.ui.theme.StageDeep
import io.github.shreyas2692.sleeptracker.ui.theme.StageLight
import io.github.shreyas2692.sleeptracker.ui.theme.StageRem
import java.time.LocalDate
import java.time.LocalTime

private const val PRIVACY_POLICY_URL =
    "https://github.com/shreyas2692/Sleep-Tracking/blob/main/PRIVACY.md"

private enum class AppTab(val label: String) {
    TODAY("Today"),
    TRENDS("Trends"),
    INSIGHTS("Insights"),
    NIGHTS("Nights"),
    SETTINGS("Settings"),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SleepTrackerApp(viewModel: AppViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var selectedTab by rememberSaveable { mutableStateOf(AppTab.TODAY) }
    var editorRecordId by rememberSaveable { mutableStateOf<Int?>(null) }
    var showEditor by rememberSaveable { mutableStateOf(false) }
    var editorSubmitted by rememberSaveable { mutableStateOf(false) }
    var detailRecord by remember { mutableStateOf<SleepRecord?>(null) }
    var deleteRecord by remember { mutableStateOf<SleepRecord?>(null) }
    var confirmClear by remember { mutableStateOf(false) }
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(state.error, state.message) {
        val notice = state.error ?: state.message ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(notice)
        viewModel.dismissNotice()
    }

    LaunchedEffect(state.completedAction) {
        if (state.completedAction == BusyAction.SAVE_NIGHT && editorSubmitted) {
            showEditor = false
            editorRecordId = null
            editorSubmitted = false
        }
        if (state.completedAction != null) viewModel.consumeCompletedAction()
    }

    if (state.status == DataStatus.NEEDS_CONFIGURATION) {
        SetupScreen(
            config = state.config,
            testing = state.testingConnection,
            result = state.connectionResult,
            validate = viewModel::validateConfig,
            onTest = viewModel::testConnection,
            onSave = viewModel::saveConfig,
        )
        return
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text(selectedTab.label, fontWeight = FontWeight.SemiBold) },
                actions = {
                    if (selectedTab != AppTab.SETTINGS) {
                        IconButton(
                            onClick = viewModel::refresh,
                            enabled = state.busyAction == null && !state.summaryLoading,
                        ) {
                            Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
        bottomBar = {
            NavigationBar(modifier = Modifier.navigationBarsPadding()) {
                AppTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
                        icon = {
                            Icon(
                                imageVector = when (tab) {
                                    AppTab.TODAY -> Icons.Default.Home
                                    AppTab.TRENDS -> Icons.Default.Star
                                    AppTab.INSIGHTS -> Icons.Default.Insights
                                    AppTab.NIGHTS -> Icons.Default.DateRange
                                    AppTab.SETTINGS -> Icons.Default.Settings
                                },
                                contentDescription = null,
                            )
                        },
                        label = { Text(tab.label, maxLines = 1) },
                    )
                }
            }
        },
        floatingActionButton = {
            if (
                selectedTab in setOf(AppTab.TODAY, AppTab.NIGHTS) &&
                state.status != DataStatus.LOADING &&
                state.busyAction == null
            ) {
                FloatingActionButton(
                    onClick = {
                        editorRecordId = null
                        editorSubmitted = false
                        showEditor = true
                    },
                ) {
                    Icon(Icons.Default.Add, contentDescription = "Add night")
                }
            }
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            when {
                state.status == DataStatus.LOADING && state.stats == null -> LoadingState()
                state.status == DataStatus.ERROR && state.stats == null -> ErrorState(
                    message = state.error ?: "The server could not be loaded.",
                    onRetry = viewModel::refresh,
                    onSettings = { selectedTab = AppTab.SETTINGS },
                )
                else -> when (selectedTab) {
                    AppTab.TODAY -> TodayScreen(
                        state = state,
                        onRecord = { detailRecord = it },
                        onRequestSummary = viewModel::requestSummary,
                    )
                    AppTab.TRENDS -> TrendsScreen(
                        state = state,
                        onRange = viewModel::selectRange,
                    )
                    AppTab.INSIGHTS -> InsightsScreen(
                        state = state,
                        onLoad = viewModel::loadInsights,
                        onRecord = { detailRecord = it },
                    )
                    AppTab.NIGHTS -> NightsScreen(
                        records = state.records,
                        enabled = state.busyAction == null,
                        onRecord = { detailRecord = it },
                        onEdit = {
                            editorRecordId = it.id
                            editorSubmitted = false
                            showEditor = true
                        },
                        onDelete = { deleteRecord = it },
                    )
                    AppTab.SETTINGS -> SettingsScreen(
                        state = state,
                        validate = viewModel::validateConfig,
                        onTest = viewModel::testConnection,
                        onSaveConfig = viewModel::saveConfig,
                        onSaveGoals = viewModel::saveGoals,
                        onClear = { confirmClear = true },
                    )
                }
            }

            if (state.busyAction != null && state.stats != null) {
                CircularProgressIndicator(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 8.dp)
                        .size(24.dp),
                    strokeWidth = 2.dp,
                )
            }
        }
    }

    if (showEditor) {
        val editorRecord = editorRecordId?.let { id -> state.records.firstOrNull { it.id == id } }
        NightEditorDialog(
            record = editorRecord,
            saving = state.busyAction != null,
            onDismiss = {
                if (state.busyAction == null) {
                    showEditor = false
                    editorRecordId = null
                    editorSubmitted = false
                }
            },
            onSave = { draft ->
                editorSubmitted = true
                editorRecord?.let { viewModel.editNight(it.id, draft) } ?: viewModel.addNight(draft)
            },
        )
    }

    detailRecord?.let { record ->
        RecordDetailDialog(
            record = record,
            onDismiss = { detailRecord = null },
            onEdit = {
                detailRecord = null
                editorRecordId = record.id
                editorSubmitted = false
                showEditor = true
            },
            onDelete = {
                detailRecord = null
                deleteRecord = record
            },
            enabled = state.busyAction == null,
        )
    }

    deleteRecord?.let { record ->
        ConfirmDialog(
            title = "Delete ${record.date}?",
            body = "This removes the selected night from the server.",
            confirmLabel = "Delete",
            destructive = true,
            onDismiss = { deleteRecord = null },
            onConfirm = {
                deleteRecord = null
                viewModel.deleteNight(record.id)
            },
        )
    }

    if (confirmClear) {
        ConfirmDialog(
            title = "Clear all records?",
            body = "This permanently removes every sleep record from the configured server.",
            confirmLabel = "Clear all",
            destructive = true,
            onDismiss = { confirmClear = false },
            onConfirm = {
                confirmClear = false
                viewModel.clearAll()
            },
        )
    }
}

@Composable
private fun SetupScreen(
    config: ServerConfig,
    testing: Boolean,
    result: String?,
    validate: (ServerConfig) -> String?,
    onTest: (ServerConfig) -> Unit,
    onSave: (ServerConfig) -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 560.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            Icon(
                Icons.Default.Star,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(42.dp),
            )
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Sleep Tracker", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("Connect to your server", style = MaterialTheme.typography.titleMedium)
            }
            ConfigEditor(
                initial = config,
                testing = testing,
                result = result,
                validate = validate,
                onTest = onTest,
                onSave = onSave,
            )
        }
    }
}

@Composable
private fun TodayScreen(
    state: AppUiState,
    onRecord: (SleepRecord) -> Unit,
    onRequestSummary: () -> Unit,
) {
    val stats = state.stats
    val records = state.records
    if (stats == null) {
        EmptyState("No summary is available.")
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 104.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Sleep overview", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("${stats.total} logged nights", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                MetricCard("Average", "${formatHours(stats.avgHours)}h", Modifier.weight(1f))
                MetricCard("Quality", formatHours(stats.avgQuality), Modifier.weight(1f))
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                MetricCard("Current streak", "${stats.currentStreak}d", Modifier.weight(1f))
                MetricCard("Best streak", "${stats.bestStreak}d", Modifier.weight(1f))
            }
        }
        stats.sleepDebt?.let { debt ->
            item {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("14-day sleep balance", style = MaterialTheme.typography.labelLarge)
                        Text(
                            debtHeadline(debt.totalDebtHours),
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        Text("Target ${formatHours(debt.need)}h", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        if (state.summaryLoading) {
            item {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Text("Updating weekly AI summary", style = MaterialTheme.typography.bodyMedium)
                }
            }
        } else if (state.aiSummary != null) {
            state.aiSummary?.let { summary ->
                item {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(8.dp),
                        color = MaterialTheme.colorScheme.secondaryContainer,
                    ) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Weekly AI summary", style = MaterialTheme.typography.labelLarge)
                            Text(summary, style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                }
            }
        } else if (stats.total >= 7) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = onRequestSummary,
                        enabled = state.busyAction == null,
                    ) {
                        Icon(Icons.Default.Star, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Generate weekly AI summary")
                    }
                    Text(
                        "Optional. Your server sends aggregate sleep statistics to its configured AI provider.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    state.summaryMessage?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        item {
            Text("Recent nights", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        }
        if (records.isEmpty()) {
            item { InlineEmpty("No nights logged yet.") }
        } else {
            items(records.take(5), key = { it.id }) { record ->
                NightRow(record = record, onClick = { onRecord(record) })
            }
        }
    }
}

@Composable
private fun MetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.heightIn(min = 96.dp),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TrendsScreen(state: AppUiState, onRange: (SeriesRange) -> Unit) {
    val response = state.seriesByRange[state.selectedRange]
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            SeriesRange.entries.forEachIndexed { index, range ->
                SegmentedButton(
                    selected = state.selectedRange == range,
                    onClick = { onRange(range) },
                    shape = SegmentedButtonDefaults.itemShape(index, SeriesRange.entries.size),
                    label = { Text(range.label) },
                )
            }
        }
        when {
            state.seriesLoading -> LoadingState(Modifier.weight(1f))
            state.seriesError != null -> ErrorState(
                message = state.seriesError,
                onRetry = { onRange(state.selectedRange) },
                modifier = Modifier.weight(1f),
            )
            response == null || response.nights.isEmpty() -> EmptyState(
                "No nights in this range.",
                Modifier.weight(1f),
            )
            else -> {
                val average = response.nights.map(SeriesNight::hours).average()
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.Bottom,
                ) {
                    Column {
                        Text("${response.nights.size} nights", style = MaterialTheme.typography.labelLarge)
                        Text(
                            "${formatHours(average)}h average",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    Text(
                        "${response.start.orEmpty()} – ${response.end.orEmpty()}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(240.dp),
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.surface,
                ) {
                    SleepLineChart(response.nights, Modifier.padding(16.dp))
                }
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp),
                ) {
                    items(response.nights.asReversed().take(30), key = { it.date }) { night ->
                        ListItem(
                            headlineContent = { Text(night.date) },
                            supportingContent = { Text(night.source?.replace('_', ' ') ?: "Sleep") },
                            trailingContent = {
                                Text("${formatHours(night.hours)}h", fontWeight = FontWeight.SemiBold)
                            },
                        )
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}

@Composable
private fun SleepLineChart(nights: List<SeriesNight>, modifier: Modifier = Modifier) {
    val lineColor = MaterialTheme.colorScheme.primary
    val qualityColor = MaterialTheme.colorScheme.tertiary
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val values = nights.map(SeriesNight::hours)
    val qualities = nights.map { it.quality }
    val max = (values.maxOrNull() ?: 8.0).coerceAtLeast(8.0)
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            ChartLegend("Hours", lineColor)
            if (qualities.any { it != null }) ChartLegend("Quality (1–5)", qualityColor)
        }
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
        ) {
            repeat(5) { index ->
                val y = size.height * index / 4f
                drawLine(gridColor, Offset(0f, y), Offset(size.width, y), strokeWidth = 1.dp.toPx())
            }
            fun xAt(index: Int): Float =
                if (values.size == 1) size.width / 2f else size.width * index / (values.size - 1).toFloat()
            if (values.size == 1) {
                val y = size.height - (values.first() / max * size.height).toFloat()
                drawCircle(lineColor, radius = 5.dp.toPx(), center = Offset(size.width / 2f, y))
            } else {
                val path = Path()
                values.forEachIndexed { index, hours ->
                    val x = xAt(index)
                    val y = size.height - (hours / max * size.height).toFloat()
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, lineColor, style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round))
            }
            // Quality overlay on its own 1–5 scale, drawn as dots joined where adjacent.
            var qualityPath: Path? = null
            qualities.forEachIndexed { index, quality ->
                if (quality == null) {
                    qualityPath?.let { drawPath(it, qualityColor, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round)) }
                    qualityPath = null
                    return@forEachIndexed
                }
                val x = xAt(index)
                val y = size.height - ((quality - 1) / 4f * size.height)
                val path = qualityPath
                if (path == null) {
                    qualityPath = Path().apply { moveTo(x, y) }
                    drawCircle(qualityColor, radius = 2.5.dp.toPx(), center = Offset(x, y))
                } else {
                    path.lineTo(x, y)
                }
            }
            qualityPath?.let { drawPath(it, qualityColor, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round)) }
        }
    }
}

@Composable
private fun ChartLegend(label: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.size(10.dp).background(color, RoundedCornerShape(5.dp)))
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun InsightsScreen(
    state: AppUiState,
    onLoad: () -> Unit,
    onRecord: (SleepRecord) -> Unit,
) {
    LaunchedEffect(Unit) { onLoad() }
    val insights = state.insights
    when {
        insights == null && state.insightsLoading -> {
            LoadingState()
            return
        }
        insights == null && state.insightsError != null -> {
            ErrorState(message = state.insightsError, onRetry = onLoad)
            return
        }
        insights == null -> {
            EmptyState("No insights are available yet.")
            return
        }
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 12.dp, 16.dp, 40.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                MetricCard("Consistency", "${insights.consistency}/100", Modifier.weight(1f))
                MetricCard("Streak", "${insights.streak}d", Modifier.weight(1f))
            }
        }
        val weekly = insights.weekly.filter { it.count > 0 }
        if (weekly.isNotEmpty()) {
            item {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.surface,
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text("Weekly averages", style = MaterialTheme.typography.labelLarge)
                        WeeklyBars(insights.weekly, Modifier.fillMaxWidth().height(120.dp))
                        weekly.lastOrNull()?.let {
                            Text(
                                "${it.label}: ${formatHours(it.avgHours)}h avg · quality ${formatHours(it.avgQuality)}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
        item {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(8.dp),
                color = MaterialTheme.colorScheme.surface,
            ) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("By day of week", style = MaterialTheme.typography.labelLarge)
                    insights.dayOfWeek.forEach { day ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Text(day.day, modifier = Modifier.width(44.dp), style = MaterialTheme.typography.bodyMedium)
                            val fraction = (day.avgHours / 12.0).coerceIn(0.0, 1.0).toFloat()
                            Box(
                                Modifier
                                    .weight(1f)
                                    .height(8.dp)
                                    .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(4.dp)),
                            ) {
                                if (fraction > 0f) {
                                    Box(
                                        Modifier
                                            .fillMaxHeight()
                                            .fillMaxWidth(fraction)
                                            .background(MaterialTheme.colorScheme.primary, RoundedCornerShape(4.dp)),
                                    )
                                }
                            }
                            Text(
                                if (day.count > 0) "${formatHours(day.avgHours)}h" else "--",
                                modifier = Modifier.width(48.dp),
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                }
            }
        }
        val monthly = insights.monthly.filter { it.count > 0 }
        if (monthly.isNotEmpty()) {
            item {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.surface,
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("Monthly trend", style = MaterialTheme.typography.labelLarge)
                        monthly.forEach { month ->
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(month.label, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text(
                                    "${formatHours(month.avgHours)}h · ${month.count} nights",
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                        }
                    }
                }
            }
        }
        if (insights.bestWorst.best.isNotEmpty()) {
            item { SectionTitle("Longest nights") }
            items(insights.bestWorst.best, key = { "best-${it.id}" }) { record ->
                NightRow(record = record, onClick = { onRecord(record) })
            }
        }
        if (insights.bestWorst.worst.isNotEmpty()) {
            item { SectionTitle("Shortest nights") }
            items(insights.bestWorst.worst, key = { "worst-${it.id}" }) { record ->
                NightRow(record = record, onClick = { onRecord(record) })
            }
        }
    }
}

@Composable
private fun WeeklyBars(weeks: List<WeeklyAverage>, modifier: Modifier = Modifier) {
    val barColor = MaterialTheme.colorScheme.primary
    val emptyColor = MaterialTheme.colorScheme.surfaceVariant
    val max = weeks.maxOfOrNull(WeeklyAverage::avgHours)?.coerceAtLeast(8.0) ?: 8.0
    Canvas(modifier = modifier) {
        if (weeks.isEmpty()) return@Canvas
        val gap = 4.dp.toPx()
        val barWidth = ((size.width - gap * (weeks.size - 1)) / weeks.size).coerceAtLeast(1f)
        weeks.forEachIndexed { index, week ->
            val x = index * (barWidth + gap)
            val height = (week.avgHours / max * size.height).toFloat()
            if (week.count == 0 || height <= 0f) {
                drawRect(
                    color = emptyColor,
                    topLeft = Offset(x, size.height - 2.dp.toPx()),
                    size = androidx.compose.ui.geometry.Size(barWidth, 2.dp.toPx()),
                )
            } else {
                drawRect(
                    color = barColor,
                    topLeft = Offset(x, size.height - height),
                    size = androidx.compose.ui.geometry.Size(barWidth, height),
                )
            }
        }
    }
}

@Composable
private fun NightsScreen(
    records: List<SleepRecord>,
    enabled: Boolean,
    onRecord: (SleepRecord) -> Unit,
    onEdit: (SleepRecord) -> Unit,
    onDelete: (SleepRecord) -> Unit,
) {
    if (records.isEmpty()) {
        EmptyState("No nights logged yet.")
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp, 4.dp, 16.dp, 104.dp),
    ) {
        items(records, key = { it.id }) { record ->
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onRecord(record) },
                color = Color.Transparent,
            ) {
                Row(
                    modifier = Modifier.padding(vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text(record.date, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text(
                            "${record.bedtime} – ${record.wake} · ${formatHours(record.hours)}h · Quality ${record.quality}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        record.sourceLabel?.let { Text(it, style = MaterialTheme.typography.labelSmall) }
                        record.stages?.let { StageMiniBar(it) }
                    }
                    if (record.source == "manual") {
                        IconButton(onClick = { onEdit(record) }, enabled = enabled) {
                            Icon(Icons.Default.Edit, contentDescription = "Edit ${record.date}")
                        }
                    }
                    IconButton(onClick = { onDelete(record) }, enabled = enabled) {
                        Icon(Icons.Default.Delete, contentDescription = "Delete ${record.date}")
                    }
                }
            }
            HorizontalDivider()
        }
    }
}

@Composable
private fun NightRow(record: SleepRecord, onClick: () -> Unit) {
    ListItem(
        modifier = Modifier.clickable(onClick = onClick),
        headlineContent = { Text(record.date, fontWeight = FontWeight.SemiBold) },
        supportingContent = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("${record.bedtime} – ${record.wake} · Quality ${record.quality}")
                record.stages?.let { StageMiniBar(it) }
            }
        },
        trailingContent = { Text("${formatHours(record.hours)}h") },
    )
    HorizontalDivider()
}

@Composable
private fun StageMiniBar(stages: SleepStages, modifier: Modifier = Modifier) {
    if (stages.totalMinutes <= 0) return
    val parts = listOf(
        stages.deep to StageDeep,
        stages.rem to StageRem,
        stages.light to StageLight,
        stages.awake to StageAwake,
    )
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = 2.dp)
            .height(5.dp),
        horizontalArrangement = Arrangement.spacedBy(1.dp),
    ) {
        parts.filter { it.first > 0 }.forEach { (minutes, color) ->
            Box(
                Modifier
                    .weight(minutes.toFloat())
                    .fillMaxHeight()
                    .background(color, RoundedCornerShape(2.dp)),
            )
        }
    }
}

@Composable
private fun SettingsScreen(
    state: AppUiState,
    validate: (ServerConfig) -> String?,
    onTest: (ServerConfig) -> Unit,
    onSaveConfig: (ServerConfig) -> Unit,
    onSaveGoals: (String, String) -> Unit,
    onClear: () -> Unit,
) {
    val uriHandler = LocalUriHandler.current
    var sleepGoal by remember(state.stats?.sleepDebt?.need) {
        mutableStateOf(state.stats?.sleepDebt?.need?.let(::formatHours).orEmpty())
    }
    var bedtimeGoal by rememberSaveable { mutableStateOf("") }
    var goalError by remember { mutableStateOf<String?>(null) }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .padding(bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        SectionTitle("Server access")
        ConfigEditor(
            initial = state.config,
            testing = state.testingConnection,
            result = state.connectionResult,
            validate = validate,
            onTest = onTest,
            onSave = onSaveConfig,
            enabled = state.busyAction == null,
        )
        HorizontalDivider()
        SectionTitle("Sleep goals")
        OutlinedTextField(
            value = sleepGoal,
            onValueChange = { sleepGoal = it; goalError = null },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Hours per night") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            isError = goalError != null,
        )
        OutlinedTextField(
            value = bedtimeGoal,
            onValueChange = { bedtimeGoal = it; goalError = null },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Bedtime goal (HH:MM)") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
            isError = goalError != null,
        )
        goalError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        Button(
            onClick = {
                goalError = validateGoals(sleepGoal, bedtimeGoal)
                if (goalError == null) onSaveGoals(sleepGoal, bedtimeGoal)
            },
            enabled = state.busyAction == null,
        ) {
            Icon(Icons.Default.Check, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Save goals")
        }
        HorizontalDivider()
        SectionTitle("Server data")
        OutlinedButton(onClick = onClear, enabled = state.busyAction == null) {
            Icon(Icons.Default.Delete, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Clear all records")
        }
        HorizontalDivider()
        SectionTitle("About")
        TextButton(onClick = { uriHandler.openUri(PRIVACY_POLICY_URL) }) {
            Icon(Icons.Default.Info, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Privacy policy")
        }
        Text(
            "Sleep Tracker is not a medical device and does not provide medical advice, diagnosis, or treatment.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ConfigEditor(
    initial: ServerConfig,
    testing: Boolean,
    result: String?,
    validate: (ServerConfig) -> String?,
    onTest: (ServerConfig) -> Unit,
    onSave: (ServerConfig) -> Unit,
    enabled: Boolean = true,
) {
    var baseUrl by rememberSaveable(initial.baseUrl) { mutableStateOf(initial.baseUrl) }
    var username by rememberSaveable(initial.username) { mutableStateOf(initial.username) }
    var password by remember(initial) { mutableStateOf(initial.password) }
    var passwordVisible by rememberSaveable { mutableStateOf(false) }
    var localError by remember { mutableStateOf<String?>(null) }
    val draft = ServerConfig(baseUrl, username, password)

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedTextField(
            value = baseUrl,
            onValueChange = { baseUrl = it; localError = null },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Server URL") },
            placeholder = { Text(if (BuildConfig.DEBUG) "http://10.0.2.2:5000" else "https://sleep.example.com") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            singleLine = true,
            isError = localError != null,
            enabled = enabled && !testing,
        )
        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Username") },
            singleLine = true,
            enabled = enabled && !testing,
        )
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Password") },
            singleLine = true,
            enabled = enabled && !testing,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Password,
                autoCorrectEnabled = false,
            ),
            visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { passwordVisible = !passwordVisible }) {
                    Icon(
                        if (passwordVisible) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        contentDescription = if (passwordVisible) "Hide password" else "Show password",
                    )
                }
            },
        )
        localError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        result?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(
                onClick = {
                    localError = validate(draft)
                    if (localError == null) onTest(draft)
                },
                enabled = enabled && !testing,
            ) {
                if (testing) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                } else {
                    Text("Test")
                }
            }
            Button(
                onClick = {
                    localError = validate(draft)
                    if (localError == null) onSave(draft)
                },
                enabled = enabled && !testing,
            ) {
                Text("Save")
            }
        }
    }
}

@Composable
private fun NightEditorDialog(
    record: SleepRecord?,
    saving: Boolean,
    onDismiss: () -> Unit,
    onSave: (NightDraft) -> Unit,
) {
    var date by rememberSaveable(record?.id) { mutableStateOf(record?.date ?: LocalDate.now().toString()) }
    var bedtime by rememberSaveable(record?.id) { mutableStateOf(record?.bedtime ?: "23:00") }
    var wake by rememberSaveable(record?.id) { mutableStateOf(record?.wake ?: "07:00") }
    var quality by rememberSaveable(record?.id) { mutableIntStateOf(record?.quality ?: 3) }
    var notes by rememberSaveable(record?.id) { mutableStateOf(record?.notes.orEmpty()) }
    var error by rememberSaveable(record?.id) { mutableStateOf<String?>(null) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth(0.92f)
                .widthIn(max = 560.dp)
                .heightIn(max = 720.dp),
            shape = RoundedCornerShape(8.dp),
            tonalElevation = 6.dp,
        ) {
            Column(
                modifier = Modifier
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        if (record == null) "Add night" else "Edit night",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                    )
                    IconButton(onClick = onDismiss, enabled = !saving) {
                        Icon(Icons.Default.Close, contentDescription = "Close")
                    }
                }
                OutlinedTextField(
                    value = date,
                    onValueChange = { date = it; error = null },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Date (YYYY-MM-DD)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = bedtime,
                        onValueChange = { bedtime = it; error = null },
                        modifier = Modifier.weight(1f),
                        label = { Text("Bedtime") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                    )
                    OutlinedTextField(
                        value = wake,
                        onValueChange = { wake = it; error = null },
                        modifier = Modifier.weight(1f),
                        label = { Text("Wake") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                    )
                }
                Text("Quality $quality", style = MaterialTheme.typography.labelLarge)
                Slider(
                    value = quality.toFloat(),
                    onValueChange = { quality = it.toInt().coerceIn(1, 5) },
                    valueRange = 1f..5f,
                    steps = 3,
                )
                OutlinedTextField(
                    value = notes,
                    onValueChange = { if (it.length <= 500) notes = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 112.dp),
                    label = { Text("Notes") },
                    supportingText = { Text("${notes.length}/500") },
                    minLines = 3,
                )
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(onClick = onDismiss, enabled = !saving) { Text("Cancel") }
                    Spacer(Modifier.width(8.dp))
                    Button(
                        onClick = {
                            val draft = NightDraft(date.trim(), bedtime.trim(), wake.trim(), quality, notes)
                            error = validateNight(draft)
                            if (error == null) onSave(draft)
                        },
                        enabled = !saving,
                    ) {
                        if (saving) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        else Text("Save")
                    }
                }
            }
        }
    }
}

@Composable
private fun RecordDetailDialog(
    record: SleepRecord,
    onDismiss: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    enabled: Boolean,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(record.date) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                DetailRow("Time", "${record.bedtime} – ${record.wake}")
                DetailRow("Duration", "${formatHours(record.hours)}h")
                DetailRow("Quality", "${record.quality} / 5")
                record.sourceLabel?.let { DetailRow("Source", it) }
                record.efficiency?.let { DetailRow("Efficiency", "${formatHours(it)}%") }
                record.stages?.let { StageSummary(it) }
                if (record.notes.isNotBlank()) {
                    HorizontalDivider()
                    Text(record.notes)
                }
            }
        },
        confirmButton = {
            if (record.source == "manual") {
                TextButton(onClick = onEdit, enabled = enabled) {
                    Icon(Icons.Default.Edit, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Edit")
                }
            }
        },
        dismissButton = {
            Row {
                TextButton(onClick = onDelete, enabled = enabled) {
                    Text("Delete", color = MaterialTheme.colorScheme.error)
                }
                TextButton(onClick = onDismiss) { Text("Close") }
            }
        },
    )
}

@Composable
private fun StageSummary(stages: SleepStages) {
    val parts = listOf(
        Triple("Deep", stages.deep, StageDeep),
        Triple("REM", stages.rem, StageRem),
        Triple("Light", stages.light, StageLight),
        Triple("Awake", stages.awake, StageAwake),
    )
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Sleep stages", style = MaterialTheme.typography.labelLarge)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(12.dp),
        ) {
            parts.filter { it.second > 0 }.forEach { (_, minutes, color) ->
                Box(
                    Modifier
                        .weight(minutes.toFloat())
                        .fillMaxHeight()
                        .background(color),
                )
            }
        }
        parts.forEach { (label, minutes, _) ->
            if (minutes > 0) DetailRow(label, formatMinutes(minutes))
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(16.dp))
        Text(value, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun ConfirmDialog(
    title: String,
    body: String,
    confirmLabel: String,
    destructive: Boolean,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(body) },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors = if (destructive) {
                    ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                        contentColor = MaterialTheme.colorScheme.onError,
                    )
                } else {
                    ButtonDefaults.buttonColors()
                },
            ) {
                Text(confirmLabel)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
}

@Composable
private fun LoadingState(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
private fun ErrorState(
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    onSettings: (() -> Unit)? = null,
) {
    Box(modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Could not load sleep data", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(message, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onRetry) { Text("Retry") }
                onSettings?.let { Button(onClick = it) { Text("Settings") } }
            }
        }
    }
}

@Composable
private fun EmptyState(message: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        InlineEmpty(message)
    }
}

@Composable
private fun InlineEmpty(message: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Icon(Icons.Default.Star, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
        Text(message, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

internal fun validateNight(draft: NightDraft): String? {
    val date = runCatching { LocalDate.parse(draft.date) }.getOrNull()
        ?: return "Date must use YYYY-MM-DD."
    if (date.toString() != draft.date) return "Date must use YYYY-MM-DD."
    if (date.isAfter(LocalDate.now())) return "Date cannot be in the future."
    val bedtime = runCatching { LocalTime.parse(draft.bedtime) }.getOrNull()
        ?: return "Bedtime must use HH:MM."
    if (bedtime.toString().take(5) != draft.bedtime || draft.bedtime.length != 5) {
        return "Bedtime must use HH:MM."
    }
    val wake = runCatching { LocalTime.parse(draft.wake) }.getOrNull()
        ?: return "Wake time must use HH:MM."
    if (wake.toString().take(5) != draft.wake || draft.wake.length != 5) {
        return "Wake time must use HH:MM."
    }
    if (draft.quality !in 1..5) return "Quality must be between 1 and 5."
    if (draft.notes.length > 500) return "Notes must be 500 characters or fewer."
    return null
}

internal fun validateGoals(sleepGoal: String, bedtimeGoal: String): String? {
    if (sleepGoal.isNotBlank()) {
        val value = sleepGoal.toDoubleOrNull()
        if (value == null || !value.isFinite() || value <= 0 || value > 24) {
            return "Sleep goal must be between 0 and 24 hours."
        }
    }
    if (bedtimeGoal.isNotBlank()) {
        val parsed = runCatching { LocalTime.parse(bedtimeGoal) }.getOrNull()
        if (parsed == null || bedtimeGoal.length != 5 || parsed.toString().take(5) != bedtimeGoal) {
            return "Bedtime goal must use HH:MM."
        }
    }
    return null
}
