package shop.remnawave.user.ui

import android.content.Context
import android.graphics.BitmapFactory
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import kotlin.concurrent.thread

/**
 * Banner images. The default Lusi banners of the app sections ship in assets/banners and are drawn
 * without the network; uploads come from the shop (same-shop /media/… paths or https), 4 MB at most.
 */
object BannerCache {
    private val images = ConcurrentHashMap<String, ImageBitmap>()
    private val defaultRule = Regex("^/api/bot/banners/default/([a-z0-9-]{1,48})\\.jpg$")
    private val pathRule = Regex("^/(api/bot/banners/default/[a-z0-9-]{1,48}\\.jpg|media/[A-Za-z0-9._-]{1,120})$")

    /** "asset:banners/app-vpn.jpg" for a bundled default, otherwise the full URL, or null when not allowed. */
    fun resolve(context: Context, base: String, url: String): String? {
        defaultRule.find(url)?.let { match ->
            val asset = "banners/${match.groupValues[1]}.jpg"
            if (try { context.assets.open(asset).close(); true } catch (_: Exception) { false }) return "asset:$asset"
        }
        return when {
            url.startsWith("https://") && url.none { it.isWhitespace() } -> url
            pathRule.matches(url) && base.isNotBlank() -> base + url
            else -> null
        }
    }

    fun get(key: String): ImageBitmap? = images[key]

    fun load(context: Context, source: String): ImageBitmap? {
        images[source]?.let { return it }
        return try {
            val bytes = if (source.startsWith("asset:")) {
                context.assets.open(source.removePrefix("asset:")).use { it.readBytes() }
            } else {
                val connection = (URL(source).openConnection() as HttpURLConnection).apply {
                    instanceFollowRedirects = false
                    connectTimeout = 10000
                    readTimeout = 15000
                    setRequestProperty("Accept", "image/jpeg,image/png,image/webp")
                }
                if (connection.responseCode !in 200..299) return null
                connection.inputStream.use { it.readBytes() }
            }
            if (bytes.size > 4 * 1024 * 1024) return null
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()?.also { images[source] = it }
        } catch (_: Exception) {
            null
        }
    }
}

@Composable
fun SectionBanner(base: String, banner: LayoutBanner?, theme: LayoutTheme, onLink: (String) -> Unit) {
    if (banner == null) return
    val context = LocalContext.current
    val source = remember(base, banner.url) { BannerCache.resolve(context, base, banner.url) } ?: return
    var image by remember(source) { mutableStateOf(BannerCache.get(source)) }
    LaunchedEffect(source) {
        if (image == null) thread { BannerCache.load(context, source)?.let { loaded -> image = loaded } }
    }
    val shape = RoundedCornerShape(theme.radius.dp)
    Box(
        Modifier.fillMaxWidth().aspectRatio(2.5f).clip(shape).background(theme.surface)
            .then(if (banner.link.isNotBlank()) Modifier.clickable { onLink(banner.link) } else Modifier)
    ) {
        image?.let { Image(it, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxWidth().aspectRatio(2.5f)) }
    }
}

enum class VpnState { OFF, CONNECTING, ON }

/** The big round button of the main screen with a glow that breathes while connected. */
@Composable
fun PowerButton(state: VpnState, theme: LayoutTheme, label: String, onClick: () -> Unit) {
    val ring by animateColorAsState(
        when (state) { VpnState.ON -> theme.success; VpnState.CONNECTING -> theme.accent2; VpnState.OFF -> theme.accent },
        label = "ring",
    )
    val pulse = rememberInfiniteTransition(label = "pulse")
    val glow by pulse.animateFloat(0.92f, 1.06f, infiniteRepeatable(tween(1400), RepeatMode.Reverse), label = "glow")
    Box(Modifier.size(236.dp), contentAlignment = Alignment.Center) {
        Box(
            Modifier.size(236.dp).scale(if (state == VpnState.OFF) 1f else glow).clip(CircleShape)
                .background(Brush.radialGradient(listOf(ring.copy(alpha = 0.35f), Color.Transparent)))
        )
        Box(
            Modifier.size(176.dp).clip(CircleShape)
                .background(Brush.verticalGradient(listOf(theme.surface2, theme.surface)))
                .border(3.dp, ring, CircleShape)
                .clickable(role = Role.Button, onClickLabel = label, onClick = onClick),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Rounded.PowerSettingsNew, contentDescription = label, tint = ring, modifier = Modifier.size(78.dp))
        }
    }
}

@Composable
fun StatusPill(text: String, color: Color, theme: LayoutTheme) {
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(theme.surface).padding(horizontal = 18.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(9.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(10.dp))
        Text(text, color = theme.text, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
    }
}

/** A layout button drawn in its configured style. */
@Composable
fun ActionButton(button: LayoutButton, theme: LayoutTheme, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val shape = RoundedCornerShape(theme.radius.dp)
    val (bg, fg) = when (button.style) {
        "primary" -> theme.accent to Color(0xFF1A0F05)
        "accent" -> theme.accent2 to Color(0xFF1A0F05)
        "danger" -> theme.surface to theme.danger
        "ghost" -> Color.Transparent to theme.text
        else -> theme.surface to theme.text
    }
    val brush = if (button.style == "primary") Brush.horizontalGradient(listOf(theme.accent, theme.accent2)) else Brush.linearGradient(listOf(bg, bg))
    Row(
        modifier.fillMaxWidth().height(56.dp).clip(shape).background(brush)
            .then(if (button.style == "ghost") Modifier.border(1.dp, theme.surface2, shape) else Modifier)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = 18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        layoutIcon(button.icon)?.let { Icon(it, contentDescription = null, tint = fg, modifier = Modifier.size(22.dp)); Spacer(Modifier.width(10.dp)) }
        Text(button.label, color = if (enabled) fg else fg.copy(alpha = 0.5f), fontWeight = FontWeight.Bold, fontSize = 16.sp, maxLines = 1,
            overflow = TextOverflow.Ellipsis)
    }
}

/** A settings-style row: icon, title, optional value, chevron or switch. */
@Composable
fun ActionRow(button: LayoutButton, theme: LayoutTheme, value: String = "", toggled: Boolean? = null, onClick: () -> Unit) {
    val color = if (button.style == "danger") theme.danger else theme.text
    Row(
        Modifier.fillMaxWidth().clickable(role = if (toggled != null) Role.Switch else Role.Button, onClick = onClick)
            .padding(horizontal = 18.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        layoutIcon(button.icon)?.let { Icon(it, contentDescription = null, tint = if (button.style == "primary") theme.accent else color, modifier = Modifier.size(24.dp)) }
        Spacer(Modifier.width(16.dp))
        Text(button.label, color = color, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        if (value.isNotBlank()) Text(value, color = theme.muted, fontSize = 14.sp)
        when (toggled) {
            null -> Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = theme.muted)
            else -> Switch(checked = toggled, onCheckedChange = { onClick() },
                colors = SwitchDefaults.colors(checkedTrackColor = theme.accent, checkedThumbColor = Color.White, uncheckedTrackColor = theme.surface2))
        }
    }
}

@Composable
fun Card(theme: LayoutTheme, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, content: @Composable () -> Unit) {
    val shape = RoundedCornerShape(theme.radius.dp)
    Column(
        modifier.fillMaxWidth().clip(shape).background(theme.surface)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(18.dp),
    ) { content() }
}

@Composable
fun TrafficCard(theme: LayoutTheme, title: String, value: String, progress: Float?, modifier: Modifier = Modifier) {
    Card(theme, modifier) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(title, color = theme.text, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Text(value, color = theme.text, fontWeight = FontWeight.Bold)
        }
        if (progress != null) {
            Spacer(Modifier.height(12.dp))
            LinearProgressIndicator(progress = { progress.coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)),
                color = theme.accent, trackColor = theme.surface2)
        }
    }
}

@Composable
fun SectionTitle(text: String, theme: LayoutTheme) {
    Text(text, color = theme.text, fontSize = 28.sp, fontWeight = FontWeight.Bold, modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 4.dp),
        textAlign = TextAlign.Center)
}

@Composable
fun Muted(text: String, theme: LayoutTheme, center: Boolean = false) {
    if (text.isBlank()) return
    Text(text, color = theme.muted, fontSize = 14.sp, lineHeight = 20.sp, textAlign = if (center) TextAlign.Center else TextAlign.Start,
        modifier = Modifier.fillMaxWidth())
}

/** Bottom tab bar: the VPN tab is a framed pill in the middle, like the references. */
@Composable
fun BottomBar(layout: AppLayout, current: String, onSelect: (String) -> Unit) {
    val theme = layout.theme
    Row(
        Modifier.fillMaxWidth().background(theme.background).navigationBarsPadding().padding(horizontal = 6.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceAround,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        layout.tabs.forEach { id ->
            val section = layout.section(id) ?: return@forEach
            val selected = id == current
            val tint = if (selected) theme.accent else theme.muted
            if (section.kind == "vpn") {
                Box(
                    Modifier.clip(RoundedCornerShape(14.dp)).border(2.dp, if (selected) theme.accent else theme.muted, RoundedCornerShape(14.dp))
                        .clickable(role = Role.Tab, onClick = { onSelect(id) }).padding(horizontal = 18.dp, vertical = 8.dp),
                ) { Text(section.title, color = tint, fontWeight = FontWeight.Bold, fontSize = 17.sp) }
            } else {
                Column(
                    Modifier.clip(RoundedCornerShape(12.dp)).clickable(role = Role.Tab, onClick = { onSelect(id) }).padding(horizontal = 6.dp, vertical = 4.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    layoutIcon(section.icon)?.let { Icon(it, contentDescription = null, tint = tint, modifier = Modifier.size(26.dp)) }
                    Text(section.title, color = tint, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
                }
            }
        }
    }
}
