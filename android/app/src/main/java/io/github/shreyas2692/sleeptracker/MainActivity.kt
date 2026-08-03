package io.github.shreyas2692.sleeptracker

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.shreyas2692.sleeptracker.ui.AppViewModel
import io.github.shreyas2692.sleeptracker.ui.SleepTrackerApp
import io.github.shreyas2692.sleeptracker.ui.theme.SleepTrackerTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SleepTrackerTheme {
                SleepTrackerApp(viewModel())
            }
        }
    }
}
