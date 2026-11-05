package shop.corgi.client.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import shop.corgi.client.core.Settings

/**
 * The «Корги Люси» brand: the same palette as the shop's apps (backend/app/mobile_layout.py defaults — corgi orange
 * #FF8A1F, warm #FFC069 on a night background). «Корги» is the brand's dark theme; light and plain dark keep the accent.
 */
object Brand {
    val Orange = Color(0xFFFF8A1F)
    val Warm = Color(0xFFFFC069)
    val Night = Color(0xFF0E0F14)
    val Surface = Color(0xFF1A1C24)
    val Surface2 = Color(0xFF252833)
    val Text = Color(0xFFF5F2EE)
    val Muted = Color(0xFF9A97A3)
    val Success = Color(0xFF3DDC84)
    val Danger = Color(0xFFFF5A6E)
    val Ink = Color(0xFF1A0F05)
}

fun brandScheme(theme: String, systemDark: Boolean, amoled: Boolean): ColorScheme {
    val dark = when (theme) { "light" -> false; "system" -> systemDark; else -> true }
    val scheme = when {
        !dark -> lightColorScheme(primary = Color(0xFFE5730F), onPrimary = Color.White, secondary = Color(0xFFB8741A),
            background = Color(0xFFFFF8F2), surface = Color(0xFFFFFFFF), surfaceVariant = Color(0xFFF6E9DD), onSurfaceVariant = Color(0xFF6D625A),
            error = Brand.Danger, outline = Color(0xFFE6D3C2))
        theme == "dark" -> darkColorScheme(primary = Brand.Orange, onPrimary = Brand.Ink, secondary = Brand.Warm,
            background = Color(0xFF101114), surface = Color(0xFF1B1C20), surfaceVariant = Color(0xFF26272C), onSurfaceVariant = Brand.Muted,
            error = Brand.Danger, outline = Color(0xFF2E3036))
        else -> darkColorScheme(primary = Brand.Orange, onPrimary = Brand.Ink, secondary = Brand.Warm, onSecondary = Brand.Ink,
            background = Brand.Night, onBackground = Brand.Text, surface = Brand.Surface, onSurface = Brand.Text,
            surfaceVariant = Brand.Surface2, onSurfaceVariant = Brand.Muted, error = Brand.Danger, outline = Brand.Surface2)
    }
    return if (dark && amoled) scheme.copy(background = Color.Black, surface = Color(0xFF0B0B0D)) else scheme
}

@Composable
fun CorgiTheme(s: Settings, content: @Composable () -> Unit) {
    val context = LocalContext.current
    val systemDark = isSystemInDarkTheme()
    val dark = when (s.theme) { "light" -> false; "system" -> systemDark; else -> true }
    var scheme = brandScheme(s.theme, systemDark, s.amoled)
    // Material You: the wallpaper's colours (Android 12+), the brand theme elsewhere.
    if (s.materialYou && Build.VERSION.SDK_INT >= 31) {
        scheme = if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        if (dark && s.amoled) scheme = scheme.copy(background = Color.Black, surface = Color(0xFF0B0B0D))
    }
    val density = LocalDensity.current
    CompositionLocalProvider(LocalDensity provides Density(density.density, density.fontScale * s.textScale)) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
