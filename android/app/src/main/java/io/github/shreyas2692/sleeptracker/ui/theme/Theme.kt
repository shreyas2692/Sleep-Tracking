package io.github.shreyas2692.sleeptracker.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.core.view.WindowCompat

// Claude design language, matching the web client (static/style.css):
// cream background, ink text, terracotta accents, serif display headers.
val Cream = Color(0xFFFAF9F5)
val Ink = Color(0xFF141413)
val Terracotta = Color(0xFFD97757)
val TerracottaDeep = Color(0xFFC4633F)

// Sleep-stage ramp shared with the web dashboard.
val StageDeep = Color(0xFF8A3A20)
val StageRem = Color(0xFFC4633F)
val StageLight = Color(0xFFDE855E)
val StageAwake = Color(0xFFEDA787)

private val LightColors = lightColorScheme(
    primary = Terracotta,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFF7E8E2),
    onPrimaryContainer = Color(0xFF8A3A20),
    secondary = TerracottaDeep,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFF5F4EF),
    onSecondaryContainer = Ink,
    tertiary = Color(0xFF4C7A43),
    onTertiary = Color.White,
    background = Cream,
    surface = Color.White,
    surfaceVariant = Color(0xFFE8E6DC),
    onSurfaceVariant = Color(0xFF4C4B45),
    outline = Color(0xFFA09E95),
    outlineVariant = Color(0xFFE8E6DC),
    onBackground = Ink,
    onSurface = Ink,
    error = Color(0xFFB3261E),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFE08B6D),
    onPrimary = Color(0xFF30302E),
    primaryContainer = Color(0xFF8A3A20),
    onPrimaryContainer = Color(0xFFF0B394),
    secondary = Color(0xFFDE855E),
    onSecondary = Color(0xFF30302E),
    secondaryContainer = Color(0xFF3E3E3A),
    onSecondaryContainer = Color(0xFFE8E6DC),
    tertiary = Color(0xFF86A97C),
    onTertiary = Color(0xFF262624),
    background = Color(0xFF262624),
    surface = Color(0xFF30302E),
    surfaceVariant = Color(0xFF3E3E3A),
    onSurfaceVariant = Color(0xFFA8A69E),
    outline = Color(0xFFA09E95),
    outlineVariant = Color(0xFF4C4B45),
    onBackground = Color(0xFFF5F4EF),
    onSurface = Color(0xFFF5F4EF),
    error = Color(0xFFFFB4AB),
)

// Serif display and headline text, sans-serif body, per the product's design language.
private val SleepTypography = Typography().let { base ->
    base.copy(
        displayLarge = base.displayLarge.copy(fontFamily = FontFamily.Serif),
        displayMedium = base.displayMedium.copy(fontFamily = FontFamily.Serif),
        displaySmall = base.displaySmall.copy(fontFamily = FontFamily.Serif),
        headlineLarge = base.headlineLarge.copy(fontFamily = FontFamily.Serif),
        headlineMedium = base.headlineMedium.copy(fontFamily = FontFamily.Serif),
        headlineSmall = base.headlineSmall.copy(fontFamily = FontFamily.Serif),
        titleLarge = base.titleLarge.copy(fontFamily = FontFamily.Serif, fontWeight = FontWeight.SemiBold),
    )
}

@Composable
fun SleepTrackerTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val scheme = if (dark) DarkColors else LightColors
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = scheme.background.toArgb()
            window.navigationBarColor = scheme.background.toArgb()
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !dark
                isAppearanceLightNavigationBars = !dark
            }
            if (Build.VERSION.SDK_INT >= 29) window.isNavigationBarContrastEnforced = false
        }
    }
    MaterialTheme(colorScheme = scheme, typography = SleepTypography, content = content)
}
