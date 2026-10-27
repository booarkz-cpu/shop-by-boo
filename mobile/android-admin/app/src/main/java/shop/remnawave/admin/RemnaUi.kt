package shop.remnawave.admin

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Remna Dark — the palette of the web admin panel (admin/src/theme.css). */
object Remna {
    val bg = Color(0xFF090D16)
    val surface = Color(0xFF0F172A)
    val surface2 = Color(0xFF131C31)
    val surface3 = Color(0xFF1A2540)
    val input = Color(0xFF0B1220)
    val line = Color(0xFF1E293B)
    val lineStrong = Color(0xFF2C3B57)
    val text = Color(0xFFE2E8F0)
    val textStrong = Color(0xFFF8FAFC)
    val muted = Color(0xFF94A3B8)
    val subtle = Color(0xFF64748B)
    val primary = Color(0xFF3B82F6)
    val primaryInk = Color(0xFF93C5FD)
    val cyan = Color(0xFF22D3EE)
    val success = Color(0xFF22C55E)
    val warning = Color(0xFFF59E0B)
    val danger = Color(0xFFEF4444)
    val radius = 14.dp
}

fun remnaColors() = darkColorScheme(
    primary = Remna.primary, onPrimary = Color.White, background = Remna.bg, onBackground = Remna.text,
    surface = Remna.surface, onSurface = Remna.text, surfaceVariant = Remna.surface2, onSurfaceVariant = Remna.muted,
    outline = Remna.lineStrong, error = Remna.danger,
)

/** Top bar like the web panel header: logo, title, the active shop and the language switch. */
@Composable
fun RemnaHeader(title: String, subtitle: String, logo: ImageBitmap?, action: String, onAction: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(Remna.primary.copy(alpha = .14f)), contentAlignment = Alignment.Center) {
            if (logo != null) Image(logo, contentDescription = null, modifier = Modifier.size(30.dp)) else Text("🐶", fontSize = 20.sp)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = Remna.textStrong, fontWeight = FontWeight.Bold, fontSize = 19.sp)
            if (subtitle.isNotBlank()) Text(subtitle, color = Remna.muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        RemnaGhost(action, onClick = onAction)
    }
}

/** Section navigation: the sidebar of the web panel as a horizontal strip of pills. */
@Composable
fun RemnaNav(items: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        items.forEach { (key, label) ->
            val on = key == selected
            Text(label, color = if (on) Remna.textStrong else Remna.muted, fontSize = 14.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(if (on) Remna.primary.copy(alpha = .16f) else Remna.surface)
                    .border(1.dp, if (on) Remna.primary.copy(alpha = .5f) else Remna.line, RoundedCornerShape(10.dp))
                    .clickable { onSelect(key) }.padding(horizontal = 14.dp, vertical = 9.dp))
        }
    }
}

@Composable
fun RemnaCard(title: String = "", hint: String = "", content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(Remna.radius)).background(Remna.surface).border(1.dp, Remna.line, RoundedCornerShape(Remna.radius))
        .padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (title.isNotBlank()) Text(title, color = Remna.textStrong, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
        if (hint.isNotBlank()) Text(hint, color = Remna.muted, fontSize = 13.sp)
        content()
    }
}

/** KPI tile of the dashboard: a label, a big number and an optional caption. */
@Composable
fun RemnaKpi(label: String, value: String, modifier: Modifier = Modifier, tone: Color = Remna.primaryInk) {
    Column(modifier.clip(RoundedCornerShape(Remna.radius)).background(Remna.surface).border(1.dp, Remna.line, RoundedCornerShape(Remna.radius)).padding(14.dp)) {
        Text(label, color = Remna.muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(6.dp))
        Text(value, color = tone, fontWeight = FontWeight.Bold, fontSize = 24.sp, fontFamily = FontFamily.Monospace)
    }
}

@Composable
fun RemnaKpiRow(vararg items: Pair<String, String>) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        items.forEach { (label, value) -> RemnaKpi(label, value, Modifier.weight(1f)) }
    }
}

enum class Tone { OK, WARN, BAD, INFO, MUTED }

fun toneColor(tone: Tone) = when (tone) {
    Tone.OK -> Remna.success; Tone.WARN -> Remna.warning; Tone.BAD -> Remna.danger; Tone.INFO -> Remna.primaryInk; Tone.MUTED -> Remna.muted
}

fun toneOf(status: String): Tone = when (status.lowercase()) {
    "paid", "fulfilled", "online", "active", "done", "completed", "sent", "enabled", "ok", "answered", "closed" -> Tone.OK
    "pending", "queued", "sending", "creating", "processing", "open", "waiting", "stale", "review" -> Tone.WARN
    "failed", "offline", "error", "creation_unknown", "refunded", "disabled", "critical", "restricted" -> Tone.BAD
    else -> Tone.MUTED
}

@Composable
fun RemnaBadge(text: String, tone: Tone = toneOf(text)) {
    val color = toneColor(tone)
    Text(text, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(color.copy(alpha = .12f)).padding(horizontal = 9.dp, vertical = 3.dp))
}

/** One row of a table card: a title, a muted second line, a status badge and optional actions. */
@Composable
fun RemnaRow(title: String, detail: String = "", badge: String = "", tone: Tone? = null, actions: @Composable (() -> Unit)? = null) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Remna.surface2).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(title, color = Remna.text, fontWeight = FontWeight.Medium, fontSize = 15.sp, modifier = Modifier.weight(1f))
            if (badge.isNotBlank()) RemnaBadge(badge, tone ?: toneOf(badge))
        }
        if (detail.isNotBlank()) Text(detail, color = Remna.muted, fontSize = 13.sp)
        if (actions != null) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { actions() }
    }
}

@Composable
fun RemnaEmpty(text: String) {
    Text(text, color = Remna.subtle, fontSize = 14.sp, modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp))
}

@Composable
fun RemnaNotice(text: String, tone: Tone = Tone.WARN) {
    val color = toneColor(tone)
    Text(text, color = color, fontSize = 14.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(color.copy(alpha = .1f)).border(1.dp, color.copy(alpha = .35f), RoundedCornerShape(12.dp)).padding(12.dp))
}

@Composable
fun RemnaPrimary(text: String, enabled: Boolean = true, modifier: Modifier = Modifier.fillMaxWidth(), onClick: () -> Unit) {
    androidx.compose.material3.Button(onClick = onClick, enabled = enabled, modifier = modifier.height(46.dp), shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Remna.primary, contentColor = Color.White)) { Text(text, fontWeight = FontWeight.SemiBold) }
}

@Composable
fun RemnaGhost(text: String, enabled: Boolean = true, danger: Boolean = false, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, enabled = enabled, shape = RoundedCornerShape(10.dp), border = BorderStroke(1.dp, if (danger) Remna.danger.copy(alpha = .5f) else Remna.lineStrong),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = if (danger) Remna.danger else Remna.text)) { Text(text, fontSize = 13.sp) }
}

@Composable
fun RemnaField(value: String, onChange: (String) -> Unit, label: String, secret: Boolean = false, singleLine: Boolean = true) {
    OutlinedTextField(value, onChange, label = { Text(label) }, singleLine = singleLine, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
        visualTransformation = if (secret) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Remna.primary, unfocusedBorderColor = Remna.line, focusedContainerColor = Remna.input,
            unfocusedContainerColor = Remna.input, focusedLabelColor = Remna.primaryInk, unfocusedLabelColor = Remna.muted, focusedTextColor = Remna.text, unfocusedTextColor = Remna.text))
}

@Composable
fun RemnaDot(tone: Tone) {
    Box(Modifier.size(9.dp).clip(CircleShape).background(toneColor(tone)))
}
