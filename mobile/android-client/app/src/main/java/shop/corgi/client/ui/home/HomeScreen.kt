package shop.corgi.client.ui.home

import android.content.Context
import android.content.Intent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColor
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateDp
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.updateTransition
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.NetworkWifi1Bar
import androidx.compose.material.icons.filled.NetworkWifi3Bar
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.SignalWifi0Bar
import androidx.compose.material.icons.filled.SignalWifi4Bar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import shop.corgi.client.BuildConfig
import shop.corgi.client.R
import shop.corgi.client.core.SubInfo
import shop.corgi.client.core.tr
import shop.corgi.client.ui.Brand
import shop.corgi.client.ui.LocalVibration
import shop.corgi.client.ui.brandScheme

/**
 * v1.5.0: the main screen (the owner's prompt of 2026-11-07). [HomeScreen] connects the view model to the app;
 * [HomeContent] only draws a [VpnUiState] — the previews below show every state in the light and the dark theme.
 * [server] and [below] are the parts that work on the store (the server picker, the provider, «Добавить»).
 */
@Composable
fun HomeScreen(connect: () -> Unit, compact: Boolean, server: @Composable () -> Unit, below: @Composable () -> Unit) {
    val context = LocalContext.current
    val model: VpnViewModel = viewModel { VpnViewModel(AndroidVpnEngine(context)) }
    val state by model.state.collectAsState()
    LaunchedEffect(model) { model.events.collect { if (it is HomeEvent.Connect) connect() } }
    // The tab may come back after the settings changed (ad blocking, profiles): read everything again.
    LaunchedEffect(Unit) { model.refresh() }
    HomeContent(
        state = state,
        version = BuildConfig.VERSION_NAME,
        compact = compact,
        onToggle = model::toggleVpn,
        onAdBlock = model::toggleAdBlock,
        onShare = { share(context) },
        server = server,
        below = below
    )
}

@Composable
fun HomeContent(
    state: VpnUiState,
    version: String,
    compact: Boolean = false,
    onToggle: () -> Unit = {},
    onAdBlock: () -> Unit = {},
    onShare: () -> Unit = {},
    server: @Composable () -> Unit = {},
    below: @Composable () -> Unit = {}
) {
    val haptic = LocalHapticFeedback.current
    val vibrate = LocalVibration.current
    val light = { if (vibrate) haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove) }
    val strong = { if (vibrate) haptic.performHapticFeedback(HapticFeedbackType.LongPress) }
    Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        Glow(state.status)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Header(version, state.streakDays) {
                light()
                onShare()
            }
            ProtectionBanner {
                light()
                if (state.status == VpnStatus.Idle && state.hasProfile) onToggle()
            }
            Column(
                Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                StatusBadge(state.status)
                // v1.6.0 (N10): the address the internet sees, with its country's flag.
                AnimatedVisibility(state.isConnected && state.externalIp.isNotEmpty(), enter = fadeIn(), exit = fadeOut()) {
                    Text(
                        listOf(state.externalFlag, state.externalIp).filter { it.isNotEmpty() }.joinToString(" "),
                        Modifier.testTag("external-ip"),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (compact) {
                    CompactSwitch(state) {
                        strong()
                        onToggle()
                    }
                } else {
                    PowerButton(state.status, enabled = buttonEnabled(state)) {
                        strong()
                        onToggle()
                    }
                }
                Stats(state)
            }
            if (state.mustChoose && state.status == VpnStatus.Idle) {
                Text(
                    tr("Сервер удалён — выберите другой", "The server was removed — pick another one", "Сервер видалено — оберіть інший"),
                    Modifier.testTag("must-choose"),
                    color = MaterialTheme.colorScheme.error
                )
            }
            if (state.error.isNotBlank()) Text(state.error, color = MaterialTheme.colorScheme.error)
            server()
            AdBlockRow(state) {
                light()
                onAdBlock()
            }
            below()
        }
    }
}

/** Two soft spots behind everything: orange at the top right, green at the bottom left; brighter when connected. */
@Composable
private fun Glow(status: VpnStatus) {
    val transition = updateTransition(status, label = "glow")
    val orange by transition.animateFloat({ tween(600) }, label = "orange") {
        when (it) {
            VpnStatus.Idle -> 0.10f
            VpnStatus.Connecting -> 0.18f
            VpnStatus.Connected -> 0.30f
        }
    }
    val green by transition.animateFloat({ tween(600) }, label = "green") {
        when (it) {
            VpnStatus.Idle -> 0.05f
            VpnStatus.Connecting -> 0.10f
            VpnStatus.Connected -> 0.22f
        }
    }
    Canvas(Modifier.fillMaxSize()) {
        val r = size.maxDimension * 0.55f
        val top = Offset(size.width * 0.95f, size.height * 0.05f)
        drawCircle(Brush.radialGradient(listOf(Brand.Orange.copy(alpha = orange), Color.Transparent), top, r), r, top)
        val bottom = Offset(size.width * 0.05f, size.height * 0.92f)
        drawCircle(Brush.radialGradient(listOf(Brand.Success.copy(alpha = green), Color.Transparent), bottom, r), r, bottom)
    }
}

/** The name with the version, the slogan right under the name; the streak and «Поделиться» on the right. */
@Composable
private fun Header(version: String, streak: Int, onShare: () -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    tr("Корги Люси", "Corgi Lusi", "Коргі Люсі"),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Black,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    "v$version",
                    Modifier
                        .clip(RoundedCornerShape(50))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Text(
                tr("Свободный интернет без лишнего Гав!", "Free internet without the extra Woof!", "Вільний інтернет без зайвого Гав!"),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("slogan")
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "🔥 " + streakText(streak),
                Modifier
                    .clip(RoundedCornerShape(50))
                    .background(MaterialTheme.colorScheme.surface)
                    .padding(horizontal = 10.dp, vertical = 6.dp)
                    .testTag("streak"),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.Bold
            )
            IconButton(onClick = onShare, Modifier.testTag("share")) {
                Icon(Icons.Filled.Share, tr("Поделиться", "Share", "Поділитися"), tint = MaterialTheme.colorScheme.onSurface)
            }
        }
    }
}

/** «ЗАЩИТА В ОДНО КАСАНИЕ» — drawn by the app (the text is never cut by the picture's crop), the corgi on the right. */
@Composable
private fun ProtectionBanner(onClick: () -> Unit) {
    val shape = RoundedCornerShape(24.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.9f))
            .border(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.2f), shape)
            .clickable(onClick = onClick)
            .padding(16.dp)
            .testTag("banner-app-vpn"),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                tr("ЗАЩИТА В ОДНО КАСАНИЕ", "PROTECTION IN ONE TAP", "ЗАХИСТ В ОДИН ДОТИК"),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                tr("Безлимит", "Unlimited", "Безліміт"),
                Modifier
                    .clip(RoundedCornerShape(50))
                    .border(1.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(50))
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
        }
        Image(painterResource(R.drawable.corgi_logo), tr("Корги", "Corgi", "Коргі"), Modifier.size(84.dp))
    }
}

@Composable
private fun StatusBadge(status: VpnStatus) {
    val transition = updateTransition(status, label = "badge")
    val color by transition.animateColor({ tween(400) }, label = "color") {
        when (it) {
            VpnStatus.Idle -> MaterialTheme.colorScheme.onSurfaceVariant
            VpnStatus.Connecting -> Brand.Warm
            VpnStatus.Connected -> Brand.Success
        }
    }
    Row(
        Modifier
            .clip(RoundedCornerShape(50))
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 14.dp, vertical = 8.dp)
            .testTag("status"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Box(Modifier.size(10.dp).clip(CircleShape).background(color))
        Text(statusText(status), style = MaterialTheme.typography.labelLarge, color = color)
    }
}

/** 180 dp: dark grey when off, a spinning ring while connecting, an orange gradient with an orange glow when on. */
@Composable
private fun PowerButton(status: VpnStatus, enabled: Boolean, onClick: () -> Unit) {
    val transition = updateTransition(status, label = "power")
    val glow by transition.animateDp({ tween(500) }, label = "glow") { if (it == VpnStatus.Connected) 28.dp else 0.dp }
    val iconColor by transition.animateColor({ tween(400) }, label = "icon") {
        when (it) {
            VpnStatus.Idle -> MaterialTheme.colorScheme.onSurfaceVariant
            VpnStatus.Connecting -> Brand.Warm
            VpnStatus.Connected -> Brand.Ink
        }
    }
    val on = status == VpnStatus.Connected
    val fill =
        if (on) {
            Brush.verticalGradient(listOf(Brand.Warm, Brand.Orange))
        } else {
            Brush.verticalGradient(listOf(MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.surface))
        }
    // v1.6.0 (N10): a pulse around the button while connecting; a disabled button is half transparent.
    Box(Modifier.size(220.dp).alpha(if (enabled) 1f else 0.5f), contentAlignment = Alignment.Center) {
        if (status == VpnStatus.Connecting) PulseRing()
        Box(
            Modifier
                .size(180.dp)
                .shadow(glow, CircleShape, ambientColor = Brand.Orange, spotColor = Brand.Orange)
                .clip(CircleShape)
                .background(fill)
                .border(2.dp, if (on) Brand.Orange else Color.White.copy(alpha = 0.08f), CircleShape)
                .clickable(enabled = enabled, onClick = onClick)
                .testTag("connect"),
            contentAlignment = Alignment.Center
        ) {
            Icon(Icons.Filled.PowerSettingsNew, statusText(status), Modifier.size(80.dp), tint = iconColor)
        }
        AnimatedVisibility(status == VpnStatus.Connecting, enter = fadeIn(), exit = fadeOut()) {
            CircularProgressIndicator(Modifier.size(196.dp), color = Brand.Warm, strokeWidth = 4.dp)
        }
    }
}

/** The ring pulses only while it is shown, so an idle screen has no endless animation (Compose UI tests wait for idle). */
@Composable
private fun PulseRing() {
    val pulse = rememberInfiniteTransition(label = "pulse")
    val ring by pulse.animateFloat(1f, 1.22f, infiniteRepeatable(tween(900), RepeatMode.Restart), label = "ring")
    val ringAlpha by pulse.animateFloat(0.45f, 0f, infiniteRepeatable(tween(900), RepeatMode.Restart), label = "ringAlpha")
    Box(
        Modifier
            .size(180.dp)
            .scale(ring)
            .alpha(ringAlpha)
            .border(3.dp, Brand.Warm, CircleShape)
            .testTag("connect-pulse")
    )
}

/** v1.6.0 (N10): idle — only with a chosen server and no change of the servers running; on — stopping waits for the change too. */
internal fun buttonEnabled(state: VpnUiState): Boolean = if (state.status == VpnStatus.Idle) state.canConnect else !state.configBusy

@Composable
private fun CompactSwitch(state: VpnUiState, onToggle: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(statusText(state.status), Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
        Switch(
            checked = state.status != VpnStatus.Idle,
            onCheckedChange = { onToggle() },
            enabled = buttonEnabled(state),
            modifier = Modifier.testTag("connect")
        )
    }
}

/** The session's time and traffic, shown only while connected. */
@Composable
private fun Stats(state: VpnUiState) {
    AnimatedVisibility(state.isConnected, enter = fadeIn() + expandVertically(), exit = fadeOut() + shrinkVertically()) {
        Row(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(20.dp))
                .background(MaterialTheme.colorScheme.surface)
                .padding(vertical = 12.dp)
                .testTag("stats"),
            horizontalArrangement = Arrangement.SpaceEvenly
        ) {
            Stat(tr("Время", "Time", "Час"), duration(state.sessionSeconds))
            Stat("↓ " + SubInfo.bytes(state.downSpeed) + "/s", SubInfo.bytes(state.downTotal))
            Stat("↑ " + SubInfo.bytes(state.upSpeed) + "/s", SubInfo.bytes(state.upTotal))
        }
    }
}

@Composable
private fun Stat(title: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 1)
        Text(title, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
    }
}

@Composable
private fun AdBlockRow(state: VpnUiState, onToggle: () -> Unit) {
    val note =
        when {
            state.adBlockNeedsGeo ->
                tr(
                    "Нужны geo-файлы: «Настройки → Маршруты → Скачать geo-файлы»",
                    "Geo files needed: «Settings → Routing → Download geo files»",
                    "Потрібні geo-файли: «Налаштування → Маршрути → Завантажити geo-файли»"
                )
            state.adBlockPending -> tr("Заработает после переподключения", "Works after reconnecting", "Запрацює після перепідключення")
            else -> ""
        }
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(Icons.Filled.Shield, null, tint = Brand.Success)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(tr("Блокировка рекламы", "Ad blocking", "Блокування реклами"), style = MaterialTheme.typography.titleSmall)
            if (note.isNotEmpty()) {
                Text(note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Switch(checked = state.adBlock, onCheckedChange = { onToggle() }, modifier = Modifier.testTag("adblock"))
    }
}

/** The bars from the measured delay (v1.6.0, N10): 3 — under 100 ms, 2 — 100–300 ms, 1 — slower, 0 — not measured or no answer. */
fun signalBars(ping: Int?): Int = when {
    ping == null || ping <= 0 -> 0
    ping < 100 -> 3
    ping <= 300 -> 2
    else -> 1
}

@Composable
fun SignalIcon(ping: Int?) {
    val bars = signalBars(ping)
    val icon =
        when (bars) {
            3 -> Icons.Filled.SignalWifi4Bar
            2 -> Icons.Filled.NetworkWifi3Bar
            1 -> Icons.Filled.NetworkWifi1Bar
            else -> Icons.Filled.SignalWifi0Bar
        }
    val tint =
        when {
            bars == 3 -> Brand.Success
            bars == 2 -> Color(0xFFF5C451)
            bars == 1 -> Brand.Warm
            ping != null && ping < 0 -> Brand.Danger // no answer: red
            else -> MaterialTheme.colorScheme.onSurfaceVariant
        }
    Icon(icon, tr("Сигнал", "Signal", "Сигнал"), Modifier.size(20.dp).testTag("signal-$bars"), tint = tint)
}

fun statusText(status: VpnStatus): String = when (status) {
    VpnStatus.Idle -> tr("Отключено", "Disconnected", "Вимкнено")
    VpnStatus.Connecting -> tr("Подключение…", "Connecting…", "Підключення…")
    VpnStatus.Connected -> tr("Подключено", "Connected", "Підключено")
}

/** «3 дня», «5 дней», «1 day» … */
fun streakText(days: Int): String {
    val mod10 = days % 10
    val mod100 = days % 100
    val few = mod10 in 2..4 && mod100 !in 12..14
    val one = mod10 == 1 && mod100 != 11
    val ru = if (one) {
        "день"
    } else if (few) {
        "дня"
    } else {
        "дней"
    }
    val uk = if (one) {
        "день"
    } else if (few) {
        "дні"
    } else {
        "днів"
    }
    return tr("$days $ru", if (days == 1) "1 day" else "$days days", "$days $uk")
}

fun duration(seconds: Long): String = "%02d:%02d:%02d".format(seconds / 3600, seconds % 3600 / 60, seconds % 60)

private fun share(context: Context) {
    val text =
        tr(
            "Корги Люси — бесплатный VPN-клиент: ",
            "Corgi Lusi — a free VPN client: ",
            "Коргі Люсі — безкоштовний VPN-клієнт: "
        ) + "https://github.com/booarkz-cpu/shop-by-boo/releases/tag/client-v${BuildConfig.VERSION_NAME}"
    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
    context.startActivity(Intent.createChooser(send, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}

// ---------------------------------------------------------------- previews: every state, light and dark

private val previewConnected =
    VpnUiState(
        status = VpnStatus.Connected,
        sessionSeconds = 3_725,
        downSpeed = 1_250_000,
        upSpeed = 84_000,
        downTotal = 412_000_000,
        upTotal = 23_000_000,
        adBlock = true,
        streakDays = 3,
        hasProfile = true
    )

@Composable
private fun PreviewServer() {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("🇩🇪", style = MaterialTheme.typography.titleLarge)
        Text("Германия №3", Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        SignalIcon(48)
    }
}

@Composable
private fun Preview(theme: String, state: VpnUiState) {
    MaterialTheme(colorScheme = brandScheme(theme, systemDark = theme != "light", amoled = false)) {
        Box(Modifier.height(900.dp)) { HomeContent(state, "1.5.0", server = { PreviewServer() }) }
    }
}

@Preview(name = "Отключено · тёмная", widthDp = 400, heightDp = 900)
@Composable
private fun IdleDark() = Preview("corgi", previewConnected.copy(status = VpnStatus.Idle, sessionSeconds = 0, adBlock = false))

@Preview(name = "Отключено · светлая", widthDp = 400, heightDp = 900)
@Composable
private fun IdleLight() = Preview("light", previewConnected.copy(status = VpnStatus.Idle, sessionSeconds = 0, adBlock = false))

@Preview(name = "Подключение · тёмная", widthDp = 400, heightDp = 900)
@Composable
private fun ConnectingDark() = Preview("corgi", previewConnected.copy(status = VpnStatus.Connecting))

@Preview(name = "Подключение · светлая", widthDp = 400, heightDp = 900)
@Composable
private fun ConnectingLight() = Preview("light", previewConnected.copy(status = VpnStatus.Connecting))

@Preview(name = "Подключено · тёмная", widthDp = 400, heightDp = 900)
@Composable
private fun ConnectedDark() = Preview("corgi", previewConnected)

@Preview(name = "Подключено · светлая", widthDp = 400, heightDp = 900)
@Composable
private fun ConnectedLight() = Preview("light", previewConnected.copy(adBlockPending = true))
