package shop.corgi.client.ui

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.animation.animateContentSize
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.QrCode2
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Sort
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.automirrored.filled.HelpOutline
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import shop.corgi.client.BuildConfig
import shop.corgi.client.core.ConfigBuilder
import shop.corgi.client.core.Ping
import shop.corgi.client.core.Scheme
import shop.corgi.client.core.Profile
import shop.corgi.client.core.Server
import shop.corgi.client.core.Settings
import shop.corgi.client.core.ServerList
import shop.corgi.client.core.SubInfo
import shop.corgi.client.core.tr
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.vpn.ClientVpnService
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

@Composable
fun ClientApp(store: Store, incoming: MutableState<String?>, connect: () -> Unit, pending: MutableState<Scheme?>) {
    var revision by remember { mutableIntStateOf(0) }
    val refresh: () -> Unit = { revision++ }
    var tab by remember { mutableIntStateOf(0) }
    var page by remember { mutableStateOf<String?>(null) }   // a page of «Настройки»
    var adding by incoming
    val s = androidx.compose.runtime.key(revision) { store.settings }
    BackHandler(enabled = page != null || tab != 0) { if (page != null) page = null else tab = 0 }
    CorgiTheme(s) {
        CompositionLocalProvider(LocalVibration provides s.vibration) {
            Scaffold(
                containerColor = MaterialTheme.colorScheme.background,
                bottomBar = {
                    NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                        listOf(Icons.Filled.Home to tr("Главная", "Home", "Головна"), Icons.Filled.Dns to tr("Серверы", "Servers", "Сервери"),
                            Icons.Filled.Settings to tr("Настройки", "Settings", "Налаштування")).forEachIndexed { i, (icon, label) ->
                            NavigationBarItem(selected = tab == i, onClick = { tab = i; page = null }, icon = { Icon(icon, label) }, label = { Text(label) })
                        }
                    }
                },
            ) { padding ->
                Box(Modifier.padding(padding).fillMaxSize()) {
                    androidx.compose.runtime.key(revision) {
                        when (tab) {
                            0 -> HomeScreen(store, connect, refresh, add = { adding = it }) { tab = 1 }
                            1 -> ServersScreen(store, refresh) { adding = "" }
                            else -> SettingsScreen(store, page, { page = it }, refresh)
                        }
                    }
                }
                adding?.let { text -> AddDialog(store, text, onDone = { adding = null; refresh() }) }
                pending.value?.let { scheme -> SchemeDialog(store, scheme) { pending.value = null; refresh() } }
            }
        }
    }
}

private fun clipboard(context: Context): String =
    context.getSystemService(ClipboardManager::class.java)?.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()

private fun scanQr(context: Context, onText: (String) -> Unit) {
    GmsBarcodeScanning.getClient(context).startScan().addOnSuccessListener { code -> onText(code.rawValue.orEmpty()) }
}

/** Pings the servers by the chosen method off the main thread and keeps the results. */
internal fun pingServers(context: Context, store: Store, servers: List<Server>, done: () -> Unit) {
    if (servers.isEmpty()) { done(); return }
    thread {
        val s = store.settings
        val result = Ping.all(servers, s) { server -> Xray.measure(context, Ping.probeConfig(server), s.pingUrl) }
        store.pings = store.pings + result
        android.os.Handler(context.mainLooper).post(done)
    }
}

internal fun updateProfiles(context: Context, store: Store, profiles: List<Profile>, done: () -> Unit) {
    thread {
        val updated = profiles.filter { it.kind == "subscription" }.map { store.update(it) }
        if (store.settings.pingAfterUpdate) {
            val s = store.settings
            val servers = updated.flatMap { it.servers() }
            store.pings = store.pings + Ping.all(servers, s) { server -> Xray.measure(context, Ping.probeConfig(server), s.pingUrl) }
        }
        android.os.Handler(context.mainLooper).post(done)
    }
}

private fun date(millis: Long): String = SimpleDateFormat("dd.MM.yy, HH:mm", Locale.ROOT).format(Date(millis))

// ---------------------------------------------------------------- Главная

@Composable
private fun HomeScreen(store: Store, connect: () -> Unit, refresh: () -> Unit, add: (String) -> Unit, openServers: () -> Unit) {
    val context = LocalContext.current
    val profile = store.active()
    // v1.5.0: the screen itself is shop.corgi.client.ui.home (VpnViewModel + HomeContent); here — the parts on the store.
    shop.corgi.client.ui.home.HomeScreen(connect = connect, compact = store.settings.connectStyle == "compact",
        server = { if (profile != null) ServerPicker(store, profile, refresh, openServers) },
        below = {
            Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                if (profile == null) {
                    Text(tr("Добавьте подписку, ссылку на сервер или конфигурацию Xray.", "Add a subscription, a server link or an Xray config.",
                        "Додайте підписку, посилання на сервер або конфігурацію Xray."), color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    Text(tr("Текущий провайдер", "Current provider", "Поточний провайдер").uppercase(), style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    ProviderCard(store, profile, expanded = null, onToggle = null, refresh = refresh)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(onClick = { add("") }, Modifier.weight(1f).height(52.dp)) {
                        Icon(Icons.Filled.Add, null); Spacer(Modifier.size(6.dp)); Text(tr("Добавить", "Add", "Додати"))
                    }
                    FilledTonalButton(onClick = { add(clipboard(context)) }, Modifier.weight(1f).height(52.dp)) {
                        Icon(Icons.Filled.ContentPaste, null); Spacer(Modifier.size(6.dp)); Text(tr("Вставить", "Paste", "Вставити"))
                    }
                    FilledTonalIconButton(onClick = { scanQr(context) { add(it) } }, Modifier.size(52.dp)) { Icon(Icons.Filled.QrCodeScanner, "QR") }
                }
                store.cachedUpdate()?.let { update ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text(tr("Доступна версия", "Version available", "Доступна версія") + " ${update.versionName}", style = MaterialTheme.typography.titleSmall)
                            TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(update.apk))) }) {
                                Text(tr("Скачать обновление", "Download the update", "Завантажити оновлення"))
                            }
                        }
                    }
                }
                if (!Xray.available()) Text(tr("В этой сборке нет движка Xray.", "This build has no Xray engine.", "У цій збірці немає рушія Xray."), color = MaterialTheme.colorScheme.error)
            }
        })
}

/**
 * The chosen server; a tap opens the list of all servers of the provider (animated), a tap on a row chooses it.
 * The same choice as in «Серверы» (store.activeProfile / activeServer), with the delays measured there.
 */
@Composable
private fun ServerPicker(store: Store, profile: Profile, refresh: () -> Unit, openServers: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    val s = store.settings
    val pings = store.pings
    val servers = if (profile.kind == "json") emptyList() else profile.servers()
    val selected = store.activeServer.toIntOrNull()?.let { servers.getOrNull(it) }
    val auto = profile.kind != "json" && selected == null
    val arrow by androidx.compose.animation.core.animateFloatAsState(if (open) 180f else 0f, label = "arrow")
    Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(24.dp), MaterialTheme.colorScheme.surface,
        if (open) MaterialTheme.colorScheme.primary.copy(alpha = 0.5f) else Color.White.copy(alpha = 0.08f))
        .animateContentSize(androidx.compose.animation.core.tween(280)).testTag("server-picker")) {
        Row(Modifier.fillMaxWidth().clickable { open = !open }.padding(14.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            when {
                profile.kind == "json" -> ServerRowContent("📄", profile.title, listOf("Xray JSON"), null, s.pingDisplay)
                auto -> ServerRowContent("⚡", tr("Автовыбор", "Auto select", "Автовибір"), listOf(tr("самый быстрый", "fastest", "найшвидший")), null, s.pingDisplay)
                else -> ServerRowContent(flagOf(selected!!.name), selected.name.removePrefix(flagOf(selected.name)).trim(), selected.labels, pings[Ping.key(selected)], s.pingDisplay)
            }
            if (profile.kind != "json" && selected != null) shop.corgi.client.ui.home.SignalIcon(pings[Ping.key(selected)])
            Icon(Icons.Filled.ExpandMore, tr("Все серверы", "All servers", "Усі сервери"), Modifier.graphicsLayer { rotationZ = arrow },
                tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (open) {
            Column(Modifier.padding(start = 8.dp, end = 8.dp, bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (servers.size > 1) ServerRow("⚡", tr("Автовыбор", "Auto select", "Автовибір"), listOf(tr("самый быстрый", "fastest", "найшвидший")), null,
                    s.pingDisplay, auto) { store.activeProfile = profile.id; store.activeServer = ConfigBuilder.AUTO; open = false; refresh() }
                servers.forEachIndexed { i, server ->
                    ServerRow(flagOf(server.name), server.name.removePrefix(flagOf(server.name)).trim(), server.labels, pings[Ping.key(server)], s.pingDisplay,
                        store.activeServer == i.toString()) { store.activeProfile = profile.id; store.activeServer = i.toString(); open = false; refresh() }
                }
                TextButton(onClick = openServers, Modifier.align(Alignment.End)) { Text(tr("Все провайдеры и пинг", "All providers and ping", "Усі провайдери й пінг")) }
            }
        }
    }
}

/** One server: the flag on the left, the name and the protocol (dim) in the middle, the delay on the right. */
@Composable
private fun ServerRow(flag: String, name: String, labels: List<String>, ping: Int?, display: String, selected: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp))
        .background(if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else Color.Transparent)
        .clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 10.dp).testTag("server-row"),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        ServerRowContent(flag, name, labels, ping, display)
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.ServerRowContent(flag: String, name: String, labels: List<String>, ping: Int?, display: String) {
    Box(Modifier.size(42.dp).clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
        if (flag.isNotBlank()) Text(flag, style = MaterialTheme.typography.titleLarge) else Icon(Icons.Filled.Dns, null, tint = MaterialTheme.colorScheme.primary)
    }
    Column(Modifier.weight(1f)) {
        Text(name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(labels.joinToString(" • "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
    }
    PingBadge(ping, if (display == "digits") "digits" else display)
}

/** A provider (subscription or links): title, update, ping, menu, traffic and term, support and site, servers count. */
@Composable
internal fun ProviderCard(store: Store, profile: Profile, expanded: Boolean?, onToggle: (() -> Unit)?, refresh: () -> Unit) {
    val context = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    var qr by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val info = profile.info
    Card(shape = RoundedCornerShape(24.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = Modifier.fillMaxWidth().testTag("provider-${profile.id}")) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (onToggle != null) Icon(if (expanded == true) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null,
                    Modifier.clickable(onClick = onToggle).padding(end = 6.dp))
                Text(profile.title, Modifier.weight(1f).clickable(enabled = onToggle != null) { onToggle?.invoke() },
                    style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (profile.kind == "subscription") FilledTonalIconButton(onClick = {
                    busy = true; updateProfiles(context, store, listOf(profile)) { busy = false; refresh() }
                }, enabled = !busy) { Icon(Icons.Filled.Refresh, tr("Обновить", "Update", "Оновити")) }
                FilledTonalIconButton(onClick = { busy = true; pingServers(context, store, profile.servers()) { busy = false; refresh() } }, enabled = !busy) {
                    Icon(Icons.Filled.Speed, tr("Пинг", "Ping", "Пінг"))
                }
                Box {
                    FilledTonalIconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreHoriz, tr("Ещё", "More", "Ще")) }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text(tr("QR для ТВ и телефона", "QR for TV and phone", "QR для ТБ і телефона")) }, leadingIcon = { Icon(Icons.Filled.QrCode2, null) },
                            onClick = { menu = false; qr = if (profile.kind == "subscription") profile.url else profile.links.joinToString("\n").ifBlank { profile.json } })
                        if (profile.kind == "subscription") DropdownMenuItem(text = { Text(tr("Копировать ссылку", "Copy link", "Копіювати посилання")) }, onClick = {
                            menu = false
                            context.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(android.content.ClipData.newPlainText("subscription", profile.url))
                        })
                        DropdownMenuItem(text = { Text(tr("Удалить", "Delete", "Видалити"), color = MaterialTheme.colorScheme.error) },
                            onClick = { menu = false; store.remove(profile.id); refresh() })
                    }
                }
            }
            if (profile.kind == "subscription" && (info.total > 0 || info.used > 0 || info.expire > 0)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(if (info.expire > 0) tr("до ", "until ", "до ") + SimpleDateFormat("dd.MM.yy", Locale.ROOT).format(Date(info.expire * 1000)) else "∞",
                        style = MaterialTheme.typography.bodySmall)
                    LinearProgressIndicator(progress = { if (info.total > 0) (info.used.toFloat() / info.total).coerceIn(0f, 1f) else 0f },
                        Modifier.weight(1f).height(6.dp).clip(RoundedCornerShape(3.dp)))
                    Text("${SubInfo.bytes(info.used)} / ${if (info.total > 0) SubInfo.bytes(info.total) else "∞"}", style = MaterialTheme.typography.bodySmall)
                }
            }
            if (info.supportUrl.isNotBlank() || info.webUrl.isNotBlank()) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (info.supportUrl.isNotBlank()) FilledTonalButton(onClick = { open(context, info.supportUrl) }) {
                    Icon(Icons.AutoMirrored.Filled.HelpOutline, null); Spacer(Modifier.size(6.dp)); Text(tr("Поддержка", "Support", "Підтримка"))
                }
                if (info.webUrl.isNotBlank()) FilledTonalButton(onClick = { open(context, info.webUrl) }) {
                    Icon(Icons.Filled.Language, null); Spacer(Modifier.size(6.dp)); Text(tr("Сайт", "Website", "Сайт"))
                }
            }
            if (info.announce.isNotBlank()) Text(info.announce, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (profile.error.isNotBlank()) Text(profile.error, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            val count = if (profile.kind == "json") 1 else profile.servers().size
            Text((if (profile.updatedAt > 0) date(profile.updatedAt) + " · " else "") + tr("серверов: ", "servers: ", "серверів: ") + count +
                (if (profile.skipped > 0) " · " + tr("пропущено ", "skipped ", "пропущено ") + profile.skipped else ""),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.align(Alignment.End))
        }
    }
    qr?.let { text -> QrDialog(text) { qr = null } }
}

private fun open(context: Context, url: String) {
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

// ---------------------------------------------------------------- Серверы

@Composable
private fun ServersScreen(store: Store, refresh: () -> Unit, add: () -> Unit) {
    val context = LocalContext.current
    val s = store.settings
    val profiles = store.profiles
    val pings = store.pings
    var query by remember { mutableStateOf("") }
    var family by remember { mutableStateOf<String?>(null) }
    var collapsed by remember { mutableStateOf(setOf<String>()) }
    var receiving by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    val all = profiles.flatMap { it.servers() }
    val families = all.map { it.family }.distinct()
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(tr("Серверы", "Servers", "Сервери"), Modifier.weight(1f), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                FilledTonalIconButton(onClick = { collapsed = if (collapsed.isEmpty()) profiles.map { it.id }.toSet() else emptySet() }) {
                    Icon(if (collapsed.isEmpty()) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, tr("Свернуть", "Collapse", "Згорнути"))
                }
                FilledTonalIconButton(onClick = {
                    val next = Settings.SORTS[(Settings.SORTS.indexOf(s.sort) + 1) % Settings.SORTS.size]
                    store.settings = s.copy(sort = next); refresh()
                }) { Icon(Icons.Filled.Sort, tr("Сортировка", "Sort", "Сортування")) }
                FilledTonalIconButton(onClick = { busy = true; updateProfiles(context, store, profiles) { busy = false; refresh() } }, enabled = !busy) {
                    Icon(Icons.Filled.Refresh, tr("Обновить все", "Update all", "Оновити всі"))
                }
                FilledTonalIconButton(onClick = { busy = true; pingServers(context, store, all) { busy = false; refresh() } }, enabled = !busy) {
                    Icon(Icons.Filled.Speed, tr("Пинг всех", "Ping all", "Пінг усіх"))
                }
                FilledTonalIconButton(onClick = add, colors = androidx.compose.material3.IconButtonDefaults.filledTonalIconButtonColors(
                    containerColor = MaterialTheme.colorScheme.primary, contentColor = MaterialTheme.colorScheme.onPrimary)) {
                    Icon(Icons.Filled.Add, tr("Добавить", "Add", "Додати"))
                }
            }
            Text(tr("серверов", "servers", "серверів") + ": ${all.size} · " + tr("провайдеров", "providers", "провайдерів") + ": ${profiles.size} · " +
                tr("сортировка", "sort", "сортування") + ": " + sortName(s.sort), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item {
            OutlinedTextField(value = query, onValueChange = { query = it }, leadingIcon = { Icon(Icons.Filled.Search, null) },
                placeholder = { Text(tr("Поиск серверов…", "Search servers…", "Пошук серверів…")) }, singleLine = true,
                shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth().testTag("search"))
        }
        if (families.size > 1) item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                item { FilterChip(selected = family == null, onClick = { family = null }, label = { Text(tr("Все", "All", "Усі")) }) }
                items(families.size) { i -> FilterChip(selected = family == families[i], onClick = { family = families[i] }, label = { Text(families[i]) }) }
            }
        }
        if (profiles.isEmpty()) item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Banner("app-locations", tr("Серверов пока нет", "No servers yet", "Серверів поки немає"),
                    tr("Добавьте подписку, ссылку или QR", "Add a subscription, a link or a QR", "Додайте підписку, посилання або QR"))
                Button(onClick = add) { Text(tr("Добавить", "Add", "Додати")) }
            }
        }
        for (profile in profiles) {
            val open = profile.id !in collapsed
            item(key = profile.id) {
                ProviderCard(store, profile, expanded = open, onToggle = { collapsed = if (open) collapsed + profile.id else collapsed - profile.id }, refresh = refresh)
            }
            if (!open) continue
            if (profile.kind == "json") {
                item(key = profile.id + "-json") {
                    ServerCard("📄", profile.title, listOf("Xray JSON"), null, s.pingDisplay, store.activeProfile == profile.id) {
                        store.activeProfile = profile.id; refresh()
                    }
                }
                continue
            }
            val servers = profile.servers()
            if (query.isBlank() && family == null && servers.size > 1) item(key = profile.id + "-auto") {
                ServerCard("⚡", tr("Автовыбор", "Auto select", "Автовибір"), listOf(tr("самый быстрый", "fastest", "найшвидший")), null, s.pingDisplay,
                    store.activeProfile == profile.id && store.activeServer == ConfigBuilder.AUTO) {
                    store.activeProfile = profile.id; store.activeServer = ConfigBuilder.AUTO; refresh()
                }
            }
            val arranged = ServerList.arrange(servers, s.sort, pings, query, family)
            for ((i, server) in arranged) item(key = profile.id + "-" + i) {
                ServerCard(flagOf(server.name), server.name.removePrefix(flagOf(server.name)).trim(), server.labels, pings[Ping.key(server)], s.pingDisplay,
                    store.activeProfile == profile.id && store.activeServer == i.toString()) {
                    store.activeProfile = profile.id; store.activeServer = i.toString(); refresh()
                }
            }
        }
        item {
            TextButton(onClick = { receiving = true }) { Text(tr("Принять подписку с телефона (ТВ)", "Receive a subscription from a phone (TV)", "Прийняти підписку з телефона (ТБ)")) }
            Spacer(Modifier.height(12.dp))
        }
    }
    if (receiving) ReceiveDialog(store) { receiving = false; refresh() }
}

private fun sortName(sort: String) = when (sort) { "ping" -> tr("по пингу", "by ping", "за пінгом"); "name" -> tr("по имени", "by name", "за назвою")
    else -> tr("по умолчанию", "default", "за замовчуванням") }

/** The flag emoji a panel puts at the start of a server's name (🇩🇪 Германия №1), else none. */
internal fun flagOf(name: String): String {
    val t = name.trim()
    if (t.length >= 4 && Character.codePointAt(t, 0) in 0x1F1E6..0x1F1FF) {
        val second = Character.charCount(Character.codePointAt(t, 0))
        if (Character.codePointAt(t, second) in 0x1F1E6..0x1F1FF) return t.substring(0, second + Character.charCount(Character.codePointAt(t, second)))
    }
    return ""
}

@Composable
private fun ServerCard(flag: String, name: String, labels: List<String>, ping: Int?, display: String, selected: Boolean, onClick: () -> Unit) {
    val colors = listOf(Color(0xFF7AA2F7), MaterialTheme.colorScheme.onSurfaceVariant, MaterialTheme.colorScheme.primary, Color(0xFFF5C451))
    Card(shape = RoundedCornerShape(20.dp), colors = CardDefaults.cardColors(containerColor = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f)
        else MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth().then(if (selected) Modifier.border(1.5.dp, MaterialTheme.colorScheme.primary,
        RoundedCornerShape(20.dp)) else Modifier).clickable(onClick = onClick).testTag("server")) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.size(44.dp).clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
                if (flag.isNotBlank()) Text(flag, style = MaterialTheme.typography.titleLarge) else Icon(Icons.Filled.Bolt, null, tint = MaterialTheme.colorScheme.primary)
            }
            Column(Modifier.weight(1f)) {
                Text(name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    labels.forEachIndexed { i, l ->
                        if (i > 0) Text("·", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(l, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.SemiBold, color = colors[i.coerceAtMost(colors.size - 1)])
                    }
                }
            }
            PingBadge(ping, display)
        }
    }
}

