package shop.corgi.client.ui.home

import android.content.Context
import android.content.Intent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColor
import androidx.compose.animation.core.LinearEasing
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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
fun HomeScreen(
    connect: () -> Unit,
    compact: Boolean,
    server: @Composable () -> Unit,
    below: @Composable () -> Unit,
    mascot: Boolean = false
) {
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
        mascot = mascot,
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
    mascot: Boolean = false,
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
            Header(version) {
                light()
                onShare()
            }
            WoofBanner {
                light()
                if (state.status == VpnStatus.Idle && state.hasProfile) onToggle()
            }
            Column(
                Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                // v1.8.1 (N12): Corgi Lusi sleeps when off, runs while connecting and is happy when on.
                if (mascot) Mascot(state.status)
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

/**
 * The name with the version, the slogan right under the name; «Поделиться» on the right.
 * v1.9.0 (the owner's master prompt v6): the slogan is «Твой интернет. Твои правила. Твоя Люси»; the day counter
 * with the flame is gone.
 */
@Composable
private fun Header(version: String, onShare: () -> Unit) {
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
                tr(
                    "Твой интернет. Твои правила. Твоя Люси",
                    "Your internet. Your rules. Your Lusi",
                    "Твій інтернет. Твої правила. Твоя Люсі"
                ),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("slogan")
            )
        }
        IconButton(onClick = onShare, Modifier.testTag("share")) {
            Icon(Icons.Filled.Share, tr("Поделиться", "Share", "Поділитися"), tint = MaterialTheme.colorScheme.onSurface)
        }
    }
}

/**
 * v1.9.3 (owner, 2026-11-11): the banner in the style of the brand — the same as the banners of the shop apps and the
 * Mini App: the paw and «Корги Люси», the orange line, the title in condensed capitals and the corgi sticker on the
 * right, on the dark background with the warm glow. The text is drawn by the app, so no crop can cut it.
 * A tap connects when there is a profile and the VPN is off.
 */
@Composable
private fun WoofBanner(onClick: () -> Unit) {
    val shape = RoundedCornerShape(24.dp)
    val condensed = remember { FontFamily(android.graphics.Typeface.create("sans-serif-condensed", android.graphics.Typeface.BOLD)) }
    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(Brush.horizontalGradient(listOf(Color(0xFF2B1A0D), Color(0xFF17171B), Color(0xFF3A2410))))
            .border(1.dp, Brand.Orange.copy(alpha = 0.35f), shape)
            .clickable(onClick = onClick)
            .padding(start = 18.dp, top = 14.dp, end = 8.dp, bottom = 14.dp)
            .testTag("banner-app-vpn"),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                "🐾 " + tr("Корги Люси", "Corgi Lusi", "Коргі Люсі"),
                Modifier.testTag("banner-brand"),
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                color = Brand.Warm
            )
            Spacer(Modifier.height(6.dp))
            Box(Modifier.width(44.dp).height(4.dp).clip(CircleShape).background(Brand.Orange))
            Spacer(Modifier.height(10.dp))
            Text(
                tr("Свободный Гав в интернете!", "Free Woof on the internet!", "Вільний Гав в інтернеті!").uppercase(),
                Modifier.testTag("banner-text"),
                fontFamily = condensed,
                fontWeight = FontWeight.Black,
                fontSize = 24.sp,
                lineHeight = 27.sp,
                color = Brand.Text
            )
        }
        Image(
            painterResource(R.drawable.banner_corgi),
            tr("Корги Люси", "Corgi Lusi", "Коргі Люсі"),
            Modifier.size(108.dp)
        )
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

/**
 * v1.9.3 (owner, 2026-11-11): Lusi with the globe. VPN off — the globe stands still; connecting — the globe glows;
 * VPN on — Lusi turns the globe: its meridians run across it. No animation runs while the VPN is off.
 */
@Composable
private fun Mascot(status: VpnStatus) {
    val text =
        when (status) {
            VpnStatus.Idle ->
                tr("Люси у глобуса: VPN выключен", "Lusi at the globe: the VPN is off", "Люсі біля глобуса: VPN вимкнено")
            VpnStatus.Connecting ->
                tr("Глобус светится: подключение", "The globe glows: connecting", "Глобус світиться: підключення")
            VpnStatus.Connected ->
                tr("Люси крутит глобус: VPN работает", "Lusi turns the globe: the VPN works", "Люсі крутить глобус: VPN працює")
        }
    val turn = if (status == VpnStatus.Connected) globeTurn() else 0f
    val glow = if (status == VpnStatus.Connecting) globeGlow() else 0f
    Box(Modifier.size(width = 196.dp, height = 160.dp).testTag("mascot-${status.name.lowercase()}")) {
        // The globe of the sticker: its centre and radius as shares of the picture (scripts/bot-banners, «location»).
        fun DrawScope.centre() = Offset(size.width * GLOBE_X, size.height * GLOBE_Y)
        Canvas(Modifier.matchParentSize()) {
            if (glow > 0f) {
                val r = size.width * GLOBE_R * 1.75f
                val halo = Brush.radialGradient(listOf(Brand.Warm.copy(alpha = 0.85f * glow), Color.Transparent), centre(), r)
                drawCircle(halo, r, centre())
            }
        }
        Image(painterResource(R.drawable.mascot_globe), text, Modifier.matchParentSize())
        val motion =
            when (status) {
                VpnStatus.Connected -> "globe-turning"
                VpnStatus.Connecting -> "globe-glowing"
                else -> "globe-still"
            }
        Canvas(Modifier.matchParentSize().testTag(motion)) {
            val r = size.width * GLOBE_R
            val c = centre()
            if (status == VpnStatus.Connecting) drawCircle(Brand.Warm.copy(alpha = 0.18f + 0.22f * glow), r, c)
            if (status == VpnStatus.Connected) {
                for (line in GlobeMotion.meridians(turn)) {
                    val a = r * kotlin.math.abs(line)
                    drawArc(
                        Color.White.copy(alpha = 0.38f),
                        startAngle = if (line >= 0f) -90f else 90f,
                        sweepAngle = 180f,
                        useCenter = false,
                        topLeft = Offset(c.x - a, c.y - r),
                        size = Size(2 * a, 2 * r),
                        style = Stroke(width = 1.5.dp.toPx())
                    )
                }
            }
        }
    }
}

private const val GLOBE_X = 0.305f
private const val GLOBE_Y = 0.48f
private const val GLOBE_R = 0.225f

/** One turn of the globe in four seconds; runs only while the VPN works. */
@Composable
private fun globeTurn(): Float {
    val t = rememberInfiniteTransition(label = "globe")
    val phase by t.animateFloat(0f, 1f, infiniteRepeatable(tween(4000, easing = LinearEasing)), label = "turn")
    return phase
}

/** The glow of the globe while connecting: breathes between dim and bright. */
@Composable
private fun globeGlow(): Float {
    val t = rememberInfiniteTransition(label = "glow")
    val level by t.animateFloat(0.35f, 1f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "level")
    return level
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
