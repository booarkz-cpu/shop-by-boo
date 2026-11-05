package shop.corgi.client.ui

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import shop.corgi.client.core.ConfigBuilder
import shop.corgi.client.core.Rule
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.vpn.ClientVpnService
import java.net.InetSocketAddress
import java.net.Socket
import java.util.Locale
import kotlin.concurrent.thread

/** RU / EN / UK by the system language. */
fun tr(ru: String, en: String, uk: String): String = when (Locale.getDefault().language) { "ru" -> ru; "uk" -> uk; else -> en }

private val Brand = Color(0xFFF2994A)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ClientApp(store: Store, incoming: String?, connect: () -> Unit) {
    var revision by remember { mutableIntStateOf(0) }
    val refresh = { revision++ }
    val dark = when (store.settings.theme) { "dark" -> true; "light" -> false; else -> isSystemInDarkTheme() }
    val colors = if (dark) darkColorScheme(primary = Brand, background = Color(0xFF0E1116), surface = Color(0xFF161B22))
        else lightColorScheme(primary = Color(0xFFD9772B))
    var tab by remember { mutableIntStateOf(0) }
    var adding by remember { mutableStateOf(incoming) }
    MaterialTheme(colorScheme = colors) {
        Scaffold(
            topBar = { TopAppBar(title = { Text(tr("Корги Люси: клиент", "Corgi Lusi: client", "Коргі Люсі: клієнт")) }) },
            bottomBar = {
                NavigationBar {
                    listOf(Icons.Filled.Home to tr("Главная", "Home", "Головна"), Icons.Filled.List to tr("Серверы", "Servers", "Сервери"),
                        Icons.Filled.Share to tr("Маршруты", "Routing", "Маршрути"), Icons.Filled.Settings to tr("Настройки", "Settings", "Налаштування"))
                        .forEachIndexed { i, (icon, label) ->
                            NavigationBarItem(selected = tab == i, onClick = { tab = i }, icon = { Icon(icon, label) }, label = { Text(label) })
                        }
                }
            },
        ) { padding ->
            Box(Modifier.padding(padding).fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                key(revision) {
                    when (tab) {
                        0 -> HomeScreen(store, connect) { adding = "" }
                        1 -> ServersScreen(store, refresh) { adding = "" }
                        2 -> RoutingScreen(store, refresh)
                        else -> SettingsScreen(store, refresh)
                    }
                }
            }
            adding?.let { text -> AddDialog(store, text, onDone = { adding = null; refresh() }) }
        }
    }
}

@Composable
private fun key(value: Int, content: @Composable () -> Unit) = androidx.compose.runtime.key(value) { content() }

@Composable
private fun HomeScreen(store: Store, connect: () -> Unit, add: () -> Unit) {
    val context = LocalContext.current
    var state by remember { mutableStateOf(ClientVpnService.current(context)) }
    DisposableEffect(Unit) {
        val listener: (String) -> Unit = { value -> android.os.Handler(android.os.Looper.getMainLooper()).post { state = value } }
        ClientVpnService.listeners.add(listener)
        onDispose { ClientVpnService.listeners.remove(listener) }
    }
    val profile = store.active()
    Column(Modifier.fillMaxSize().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Spacer(Modifier.height(24.dp))
        val on = state == ClientVpnService.STATE_ON
        Box(Modifier.size(180.dp).background(if (on) Brand else MaterialTheme.colorScheme.surface, CircleShape)
            .clickable(enabled = profile != null) { if (state == ClientVpnService.STATE_OFF) connect() else ClientVpnService.stop(context) }
            .testTag("connect"), contentAlignment = Alignment.Center) {
            Text(when (state) {
                ClientVpnService.STATE_ON -> tr("Отключить", "Disconnect", "Вимкнути")
                ClientVpnService.STATE_CONNECTING -> tr("Подключение…", "Connecting…", "Підключення…")
                else -> tr("Подключить", "Connect", "Підключити")
            }, style = MaterialTheme.typography.titleLarge)
        }
        if (profile == null) {
            Text(tr("Добавьте подписку, ссылку на сервер или конфигурацию Xray.", "Add a subscription, a server link or an Xray config.",
                "Додайте підписку, посилання на сервер або конфігурацію Xray."))
            Button(onClick = add) { Text(tr("Добавить", "Add", "Додати")) }
        } else {
            val server = store.activeServer
            val name = if (profile.kind == "json") profile.name else if (server == ConfigBuilder.AUTO) tr("Самый быстрый", "Fastest", "Найшвидший")
                else profile.servers().getOrNull(server.toIntOrNull() ?: -1)?.name ?: tr("Самый быстрый", "Fastest", "Найшвидший")
            Text(profile.name, style = MaterialTheme.typography.titleMedium)
            Text(name)
        }
        ClientVpnService.lastError(context).takeIf { it.isNotBlank() && state == ClientVpnService.STATE_OFF }?.let { Text(it, color = Color(0xFFE5534B)) }
        if (!Xray.available()) Text(tr("В этой сборке нет движка Xray.", "This build has no Xray engine.", "У цій збірці немає рушія Xray."), color = Color(0xFFE5534B))
    }
}

@Composable
private fun ServersScreen(store: Store, refresh: () -> Unit, add: () -> Unit) {
    val context = LocalContext.current
    var pings by remember { mutableStateOf(mapOf<String, String>()) }
    var qr by remember { mutableStateOf<String?>(null) }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = add) { Text(tr("Добавить", "Add", "Додати")) }
                OutlinedButton(onClick = {
                    thread { store.profiles.forEach { store.update(it) }; android.os.Handler(context.mainLooper).post(refresh) }
                }) { Text(tr("Обновить все", "Update all", "Оновити всі")) }
            }
        } }
        for (profile in store.profiles) {
            item(key = profile.id) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text(profile.name, style = MaterialTheme.typography.titleMedium)
                        Text(when (profile.kind) { "subscription" -> tr("Подписка", "Subscription", "Підписка"); "json" -> "Xray JSON"; else -> tr("Ссылки", "Links", "Посилання") }
                            + (if (profile.skipped > 0) " · " + tr("пропущено", "skipped", "пропущено") + " ${profile.skipped}" else "")
                            + (if (profile.error.isNotBlank()) " · ${profile.error}" else ""), style = MaterialTheme.typography.bodySmall)
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            if (profile.kind == "subscription") TextButton(onClick = {
                                thread { store.update(profile); android.os.Handler(context.mainLooper).post(refresh) }
                            }) { Text(tr("Обновить", "Update", "Оновити")) }
                            TextButton(onClick = { qr = if (profile.kind == "subscription") profile.url else profile.links.joinToString("\n").ifBlank { profile.json } }) {
                                Text(tr("QR для ТВ", "QR for TV", "QR для ТБ"))
                            }
                            TextButton(onClick = { store.remove(profile.id); refresh() }) { Text(tr("Удалить", "Delete", "Видалити")) }
                        }
                        if (profile.kind != "json") {
                            ServerRow(tr("Самый быстрый (автовыбор)", "Fastest (automatic)", "Найшвидший (автовибір)"), "",
                                store.activeProfile == profile.id && store.activeServer == ConfigBuilder.AUTO) {
                                store.activeProfile = profile.id; store.activeServer = ConfigBuilder.AUTO; refresh()
                            }
                            profile.servers().forEachIndexed { i, server ->
                                ServerRow(server.name, "${server.protocol} · ${pings[server.link] ?: ""}",
                                    store.activeProfile == profile.id && store.activeServer == i.toString()) {
                                    store.activeProfile = profile.id; store.activeServer = i.toString(); refresh()
                                }
                            }
                            TextButton(onClick = {
                                thread {
                                    val result = profile.servers().associate { s -> s.link to tcpPing(s.host, s.port) }
                                    android.os.Handler(context.mainLooper).post { pings = pings + result }
                                }
                            }) { Text(tr("Проверить задержку", "Test latency", "Перевірити затримку")) }
                        } else {
                            ServerRow(profile.name, "Xray JSON", store.activeProfile == profile.id) { store.activeProfile = profile.id; refresh() }
                        }
                    }
                }
            }
        }
    }
    qr?.let { text -> QrDialog(text) { qr = null } }
}

@Composable
private fun ServerRow(title: String, subtitle: String, selected: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        RadioButton(selected = selected, onClick = onClick)
        Column { Text(title); if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodySmall) }
    }
}

/** TCP connect time to the server (no traffic through the tunnel). */
private fun tcpPing(host: String, port: Int): String = try {
    val start = System.nanoTime()
    Socket().use { it.connect(InetSocketAddress(host, port), 3000) }
    "${(System.nanoTime() - start) / 1_000_000} ms"
} catch (_: Exception) { tr("нет ответа", "no answer", "немає відповіді") }

@Composable
private fun AddDialog(store: Store, initial: String, onDone: () -> Unit) {
    val context = LocalContext.current
    var text by remember { mutableStateOf(initial) }
    var error by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDone, title = { Text(tr("Добавить", "Add", "Додати")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(tr("Ссылка на подписку (https://…), ссылки vless://, vmess://, trojan://, ss://, socks://, wireguard:// или JSON Xray.",
                    "A subscription URL (https://…), vless://, vmess://, trojan://, ss://, socks://, wireguard:// links or an Xray JSON.",
                    "Посилання на підписку (https://…), посилання vless://, vmess://, trojan://, ss://, socks://, wireguard:// або JSON Xray."),
                    style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(value = text, onValueChange = { text = it }, modifier = Modifier.fillMaxWidth().height(140.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = {
                        val clip = context.getSystemService(ClipboardManager::class.java)?.primaryClip
                        text = clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()
                    }) { Text(tr("Вставить", "Paste", "Вставити")) }
                    OutlinedButton(onClick = {
                        GmsBarcodeScanning.getClient(context).startScan()
                            .addOnSuccessListener { code -> text = code.rawValue.orEmpty() }
                            .addOnFailureListener { error = tr("Сканер недоступен", "Scanner unavailable", "Сканер недоступний") }
                    }) { Text(tr("Сканировать QR", "Scan QR", "Сканувати QR")) }
                }
                if (error.isNotBlank()) Text(error, color = Color(0xFFE5534B))
            }
        },
        confirmButton = {
            Button(onClick = {
                try {
                    val profile = store.add(text)
                    if (profile.kind == "subscription") thread { store.update(profile); android.os.Handler(context.mainLooper).post(onDone) } else onDone()
                } catch (exc: Exception) { error = exc.message ?: tr("Не удалось добавить", "Could not add", "Не вдалося додати") }
            }) { Text(tr("Добавить", "Add", "Додати")) }
        },
        dismissButton = { TextButton(onClick = onDone) { Text(tr("Отмена", "Cancel", "Скасувати")) } })
}

@Composable
private fun QrDialog(text: String, onDone: () -> Unit) {
    val bitmap = remember(text) {
        val matrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 640, 640)
        Bitmap.createBitmap(640, 640, Bitmap.Config.RGB_565).apply {
            for (x in 0 until 640) for (y in 0 until 640) setPixel(x, y, if (matrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
        }
    }
    AlertDialog(onDismissRequest = onDone, confirmButton = { TextButton(onClick = onDone) { Text("OK") } },
        title = { Text(tr("Отсканируйте на телевизоре или телефоне", "Scan on the TV or phone", "Відскануйте на телевізорі або телефоні")) },
        text = { Image(bitmap.asImageBitmap(), null, Modifier.size(260.dp)) })
}

@Composable
private fun RoutingScreen(store: Store, refresh: () -> Unit) {
    val context = LocalContext.current
    val s = store.settings
    var rule by remember { mutableStateOf("") }
    var action by remember { mutableStateOf("direct") }
    var message by remember { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        item { Text(tr("Что идёт через VPN", "What goes through the VPN", "Що йде через VPN"), style = MaterialTheme.typography.titleMedium) }
        items(listOf("global" to tr("Всё через VPN", "Everything", "Усе через VPN"),
            "bypass_lan" to tr("Всё, кроме локальной сети", "All but the local network", "Усе, крім локальної мережі"),
            "bypass_ru" to tr("Российские сайты напрямую", "Russian sites direct", "Російські сайти напряму"),
            "custom" to tr("Свои правила", "Own rules", "Власні правила"))) { (key, label) ->
            ServerRow(label, "", s.routing == key) { store.settings = s.copy(routing = key); refresh() }
        }
        item { Text(tr("Правила (домен, IP, geosite:, geoip:)", "Rules (domain, IP, geosite:, geoip:)", "Правила (домен, IP, geosite:, geoip:)"), style = MaterialTheme.typography.titleMedium) }
        items(s.rules) { r ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${r.match} → ${r.action}", Modifier.weight(1f))
                TextButton(onClick = { store.settings = s.copy(rules = s.rules - r); refresh() }) { Text("✕") }
            }
        }
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(value = rule, onValueChange = { rule = it }, label = { Text("example.com / 10.0.0.0/8 / geosite:category-ads-all") }, modifier = Modifier.fillMaxWidth())
            Row { Rule.ACTIONS.forEach { a -> Row(verticalAlignment = Alignment.CenterVertically) { RadioButton(action == a, { action = a }); Text(a) } } }
            Button(onClick = {
                try { store.settings = s.copy(rules = s.rules + Rule(Rule.normalize(rule), action)); rule = ""; refresh() }
                catch (exc: Exception) { message = tr("Неверное правило", "Invalid rule", "Невірне правило") }
            }) { Text(tr("Добавить правило", "Add rule", "Додати правило")) }
        } }
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(if (store.geoReady()) tr("Geo-файлы загружены", "Geo files present", "Geo-файли завантажено") else
                tr("Для geoip:/geosite: нужны geo-файлы", "geoip:/geosite: need the geo files", "Для geoip:/geosite: потрібні geo-файли"))
            OutlinedButton(onClick = {
                message = tr("Загрузка…", "Downloading…", "Завантаження…")
                thread {
                    val result = runCatching { store.downloadGeo() }.fold({ tr("Готово", "Done", "Готово") }, { it.message ?: "error" })
                    android.os.Handler(context.mainLooper).post { message = result; refresh() }
                }
            }) { Text(tr("Скачать geo-файлы", "Download geo files", "Завантажити geo-файли")) }
            if (message.isNotBlank()) Text(message)
        } }
    }
}

@Composable
private fun SettingsScreen(store: Store, refresh: () -> Unit) {
    val context = LocalContext.current
    val s = store.settings
    var dns by remember { mutableStateOf(s.dns.joinToString(", ")) }
    var picking by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Toggle(tr("Фрагментация TLS ClientHello", "TLS ClientHello fragmentation", "Фрагментація TLS ClientHello"), s.fragment) {
                store.settings = s.copy(fragment = it); refresh()
            }
            Text(tr("Помогает, когда провайдер режет TLS по SNI. Для TLS-серверов; REALITY не затрагивает.",
                "Helps when the provider blocks TLS by SNI. For TLS servers; REALITY is not affected.",
                "Допомагає, коли провайдер ріже TLS за SNI. Для TLS-серверів; REALITY не зачіпає."), style = MaterialTheme.typography.bodySmall)
            Toggle("IPv6", s.ipv6) { store.settings = s.copy(ipv6 = it); refresh() }
        } }
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(value = dns, onValueChange = { dns = it }, label = { Text("DNS") }, modifier = Modifier.fillMaxWidth())
            TextButton(onClick = {
                val list = dns.split(",", " ").map { it.trim() }.filter { it.isNotBlank() }.take(4)
                if (list.isNotEmpty()) { store.settings = s.copy(dns = list); refresh() }
            }) { Text(tr("Сохранить DNS", "Save DNS", "Зберегти DNS")) }
        } }
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(tr("Приложения", "Apps", "Застосунки"), style = MaterialTheme.typography.titleMedium)
            listOf("all" to tr("Все через VPN", "All through VPN", "Усі через VPN"), "only" to tr("Только выбранные", "Only selected", "Лише вибрані"),
                "except" to tr("Все, кроме выбранных", "All but selected", "Усі, крім вибраних")).forEach { (key, label) ->
                ServerRow(label, "", s.appsMode == key) { store.settings = s.copy(appsMode = key); refresh() }
            }
            if (s.appsMode != "all") OutlinedButton(onClick = { picking = true }) {
                Text(tr("Выбрать приложения", "Choose apps", "Вибрати застосунки") + " (${s.apps.size})")
            }
        } }
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(tr("Kill switch", "Kill switch", "Kill switch"), style = MaterialTheme.typography.titleMedium)
            Text(tr("Android блокирует интернет без VPN сам: «Постоянная VPN» и «Блокировать соединения без VPN» в настройках системы.",
                "Android blocks traffic without the VPN itself: «Always-on VPN» and «Block connections without VPN» in system settings.",
                "Android блокує інтернет без VPN сам: «Постійна VPN» і «Блокувати з'єднання без VPN» у налаштуваннях системи."),
                style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { context.startActivity(Intent(AndroidSettings.ACTION_VPN_SETTINGS)) }) {
                Text(tr("Открыть настройки VPN", "Open VPN settings", "Відкрити налаштування VPN"))
            }
        } }
        item { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(tr("Тема", "Theme", "Тема"), style = MaterialTheme.typography.titleMedium)
            listOf("system" to tr("Как в системе", "System", "Як у системі"), "dark" to tr("Тёмная", "Dark", "Темна"), "light" to tr("Светлая", "Light", "Світла"))
                .forEach { (key, label) -> ServerRow(label, "", s.theme == key) { store.settings = s.copy(theme = key); refresh() } }
            Text("Xray ${Xray.version().ifBlank { "—" }}", style = MaterialTheme.typography.bodySmall)
        } }
    }
    if (picking) AppsDialog(context, s.apps) { chosen -> if (chosen != null) store.settings = s.copy(apps = chosen); picking = false; refresh() }
}

@Composable
private fun Toggle(label: String, value: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f)); Switch(checked = value, onCheckedChange = onChange)
    }
}

@Composable
private fun AppsDialog(context: Context, initial: Set<String>, onDone: (Set<String>?) -> Unit) {
    val apps = remember {
        val pm = context.packageManager
        pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), PackageManager.MATCH_ALL)
            .map { it.activityInfo.packageName to it.loadLabel(pm).toString() }.distinctBy { it.first }
            .filter { it.first != context.packageName }.sortedBy { it.second.lowercase() }
    }
    var chosen by remember { mutableStateOf(initial) }
    AlertDialog(onDismissRequest = { onDone(null) }, title = { Text(tr("Приложения", "Apps", "Застосунки")) },
        text = {
            LazyColumn(Modifier.height(420.dp)) {
                items(apps) { (pkg, label) ->
                    Row(Modifier.fillMaxWidth().clickable { chosen = if (pkg in chosen) chosen - pkg else chosen + pkg }, verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = pkg in chosen, onCheckedChange = { chosen = if (it) chosen + pkg else chosen - pkg }); Text(label)
                    }
                }
            }
        },
        confirmButton = { Button(onClick = { onDone(chosen) }) { Text("OK") } },
        dismissButton = { TextButton(onClick = { onDone(null) }) { Text(tr("Отмена", "Cancel", "Скасувати")) } })
}
