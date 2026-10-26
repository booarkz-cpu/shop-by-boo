package shop.remnawave.user.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AccountBalanceWallet
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.BugReport
import androidx.compose.material.icons.rounded.CardGiftcard
import androidx.compose.material.icons.rounded.Chat
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.CreditCard
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.EmojiEvents
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.Group
import androidx.compose.material.icons.rounded.HeadsetMic
import androidx.compose.material.icons.rounded.Help
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Language
import androidx.compose.material.icons.rounded.Link
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Logout
import androidx.compose.material.icons.rounded.MonitorHeart
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material.icons.rounded.Public
import androidx.compose.material.icons.rounded.QrCode2
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.RocketLaunch
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material.icons.rounded.Send
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Smartphone
import androidx.compose.material.icons.rounded.Star
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material.icons.rounded.WorkspacePremium
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector

/** Icon names of the layout (backend/app/mobile_layout.py ICONS) → Material icons. */
fun layoutIcon(name: String): ImageVector? = when (name) {
    "power" -> Icons.Rounded.PowerSettingsNew
    "shield" -> Icons.Rounded.Shield
    "globe" -> Icons.Rounded.Public
    "star" -> Icons.Rounded.Star
    "crown" -> Icons.Rounded.WorkspacePremium
    "user" -> Icons.Rounded.Person
    "settings" -> Icons.Rounded.Settings
    "headset" -> Icons.Rounded.HeadsetMic
    "message" -> Icons.Rounded.Chat
    "send" -> Icons.Rounded.Send
    "bell" -> Icons.Rounded.Notifications
    "bug" -> Icons.Rounded.BugReport
    "rocket" -> Icons.Rounded.RocketLaunch
    "gift" -> Icons.Rounded.CardGiftcard
    "wallet" -> Icons.Rounded.AccountBalanceWallet
    "card" -> Icons.Rounded.CreditCard
    "users" -> Icons.Rounded.Group
    "heart" -> Icons.Rounded.Favorite
    "smartphone" -> Icons.Rounded.Smartphone
    "plus" -> Icons.Rounded.Add
    "copy" -> Icons.Rounded.ContentCopy
    "share" -> Icons.Rounded.Share
    "link" -> Icons.Rounded.Link
    "key" -> Icons.Rounded.Key
    "lock" -> Icons.Rounded.Lock
    "info" -> Icons.Rounded.Info
    "file" -> Icons.Rounded.Description
    "help" -> Icons.Rounded.Help
    "server" -> Icons.Rounded.Dns
    "activity" -> Icons.Rounded.MonitorHeart
    "zap" -> Icons.Rounded.Bolt
    "clock" -> Icons.Rounded.Schedule
    "refresh" -> Icons.Rounded.Refresh
    "logout" -> Icons.Rounded.Logout
    "language" -> Icons.Rounded.Language
    "sliders" -> Icons.Rounded.Tune
    "qr" -> Icons.Rounded.QrCode2
    "download" -> Icons.Rounded.Download
    "trophy" -> Icons.Rounded.EmojiEvents
    "home" -> Icons.Rounded.Home
    else -> null
}

fun colorScheme(theme: LayoutTheme): ColorScheme = darkColorScheme(
    primary = theme.accent,
    onPrimary = Color(0xFF1A0F05),
    secondary = theme.accent2,
    onSecondary = Color(0xFF1A0F05),
    background = theme.background,
    onBackground = theme.text,
    surface = theme.surface,
    onSurface = theme.text,
    surfaceVariant = theme.surface2,
    onSurfaceVariant = theme.muted,
    error = theme.danger,
    outline = theme.surface2,
)

/** Country code → flag emoji ("NL" → 🇳🇱). */
fun flag(country: String): String {
    val code = country.trim().uppercase()
    if (!Regex("^[A-Z]{2}$").matches(code)) return "🌐"
    return code.map { String(Character.toChars(0x1F1E6 + (it - 'A'))) }.joinToString("")
}
