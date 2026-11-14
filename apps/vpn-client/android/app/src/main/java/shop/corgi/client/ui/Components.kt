package shop.corgi.client.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import shop.corgi.client.core.Ping
import shop.corgi.client.core.tr

/** «Стекло»: a translucent surface with a thin light border over the deep background (the brand's dark look). */
fun Modifier.glass(shape: androidx.compose.ui.graphics.Shape, tint: Color, border: Color = Color.White.copy(alpha = 0.08f)): Modifier =
    this.clip(shape).background(tint.copy(alpha = 0.72f)).border(1.dp, border, shape)

/**
 * The brand banner (assets/banners, the shop apps' artwork): the picture alone in a rounded card — nothing is written
 * over it — and the title and hint under it.
 */
@Composable
fun Banner(asset: String, title: String, subtitle: String = "") {
    val context = LocalContext.current
    val bitmap = remember(asset) { runCatching { context.assets.open("banners/$asset.jpg").use { BitmapFactory.decodeStream(it) } }.getOrNull() }
    val shape = RoundedCornerShape(24.dp)
    Column(Modifier.fillMaxWidth().glass(shape, MaterialTheme.colorScheme.surface).testTag("banner-$asset")) {
        Box(Modifier.fillMaxWidth().height(140.dp).padding(8.dp).clip(RoundedCornerShape(18.dp)).background(MaterialTheme.colorScheme.surfaceVariant)) {
            bitmap?.let { Image(it.asImageBitmap(), null, Modifier.fillMaxWidth().height(140.dp), contentScale = ContentScale.Crop) }
        }
        Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 14.dp, top = 2.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
fun Section(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title.uppercase(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 4.dp, top = 8.dp))
        Card(shape = RoundedCornerShape(20.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
            Column(Modifier.padding(vertical = 4.dp)) { content() }
        }
    }
}

@Composable
fun Glyph(icon: ImageVector, tint: Color = MaterialTheme.colorScheme.primary) {
    Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(tint.copy(alpha = 0.16f)), contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = tint)
    }
}

/** A menu row: icon, title, a hint under it, the current value on the right and an arrow. */
@Composable
fun NavRow(icon: ImageVector, title: String, value: String = "", hint: String = "", onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Glyph(icon)
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            if (hint.isNotBlank()) Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (value.isNotBlank()) Text(value, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun ToggleRow(title: String, hint: String = "", value: Boolean, icon: ImageVector? = null, onChange: (Boolean) -> Unit) {
    val haptic = LocalHapticFeedback.current
    val vibrate = LocalVibration.current
    Row(Modifier.fillMaxWidth().clickable { if (vibrate) haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove); onChange(!value) }
        .padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        icon?.let { Glyph(it) }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            if (hint.isNotBlank()) Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked = value, onCheckedChange = { if (vibrate) haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove); onChange(it) })
    }
}

/** One of a few values as chips. */
@Composable
fun ChoiceRow(title: String, hint: String = "", options: List<Pair<String, String>>, value: String, onChange: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        if (hint.isNotBlank()) Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        androidx.compose.foundation.lazy.LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(options.size) { i ->
                val (key, label) = options[i]
                FilterChip(selected = key == value, onClick = { onChange(key) }, label = { Text(label) })
            }
        }
    }
}

/** The delay as the user chose to see it: digits, a bar, both, or a dot. */
@Composable
fun PingBadge(ms: Int?, display: String) {
    val level = Ping.level(ms)
    val color = when (level) { 1 -> Brand.Success; 2 -> Color(0xFFF5C451); 3 -> Brand.Danger; else -> MaterialTheme.colorScheme.onSurfaceVariant }
    val text = when { ms == null -> ""; ms < 0 -> tr("нет ответа", "timeout", "немає відповіді"); else -> "$ms ms" }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        if (display == "dots" || display == "digits") Box(Modifier.size(10.dp).clip(CircleShape).background(color))
        if (display == "bar" || display == "both") Row(horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.Bottom) {
            val bars = when (level) { 1 -> 4; 2 -> 2; 3 -> 1; else -> 0 }
            for (b in 1..4) Box(Modifier.size(width = 4.dp, height = (4 + b * 3).dp).clip(RoundedCornerShape(1.dp))
                .background(if (b <= bars) color else MaterialTheme.colorScheme.outline))
        }
        if (display != "dots" && display != "bar" && text.isNotBlank()) Text(text, style = MaterialTheme.typography.bodySmall, color = color)
        // v1.6.0 (N10): the Wi-Fi bars next to the digits (green < 100 ms, yellow 100–300 ms, red — no answer).
        if (display == "digits" && ms != null) shop.corgi.client.ui.home.SignalIcon(ms)
    }
}

val LocalVibration = androidx.compose.runtime.staticCompositionLocalOf { true }
