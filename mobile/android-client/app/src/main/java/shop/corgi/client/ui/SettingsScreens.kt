package shop.corgi.client.ui

import android.app.Activity
import android.app.StatusBarManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon as AndroidIcon
import android.os.Build
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Route
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import shop.corgi.client.BuildConfig
import shop.corgi.client.R
import shop.corgi.client.core.I18n
import shop.corgi.client.core.Settings
import shop.corgi.client.core.tr
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.vpn.QuickTile
import shop.corgi.client.vpn.UpdateJob
import kotlin.concurrent.thread

/** «Настройки»: the menu, and each of its pages (``page``). Every setting is here — nothing needs a file or a command. */
@Composable
fun SettingsScreen(store: Store, page: String?, open: (String?) -> Unit, refresh: () -> Unit) {
    val s = store.settings
    val context = LocalContext.current
    val save: (Settings) -> Unit = { store.settings = it; refresh() }
    if (page == null) { SettingsMenu(store, open, refresh); return }
    val title = PAGES.firstOrNull { it.first == page }?.second?.invoke() ?: ""
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { open(null) }, Modifier.testTag("back")) { Icon(Icons.AutoMirrored.Filled.ArrowBack, tr("Назад", "Back", "Назад")) }
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        }
        when (page) {
            "routing" -> RoutingScreen(store, refresh)
            // v1.6.2: the apps screen has its own LazyColumn — inside a lazy item it got an unbounded height.
            "apps" -> AppsPage(store, s, save)
            else -> LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    when (page) {
                        "appearance" -> AppearancePage(s, save)
                        "connection" -> ConnectionPage(s, save)
                        "tunnel" -> TunnelPage(store, s, save)
                        "schemes" -> SchemesPage()
                        "backup" -> BackupPage(store, refresh)
                        "logs" -> LogsPage(store, s, save)
                        "providers" -> ProvidersPage(s) { save(it); UpdateJob.schedule(context) }
                        "ping" -> PingPage(s, save)
                        "about" -> AboutPage(store)
                        "stats" -> StatsPage(store)
                        "netlog" -> NetworkLogPage(store, s, save)
                    }
                }
            }
        }
    }
}

private val PAGES: List<Pair<String, () -> String>> = listOf(
    "apps" to { tr("Прокси по приложениям", "Per-app proxy", "Проксі за застосунками") },
    "appearance" to { tr("Оформление", "Appearance", "Оформлення") },
    "routing" to { tr("Маршрутизация", "Routing", "Маршрутизація") },
    "connection" to { tr("Соединение", "Connection", "З'єднання") },
    "tunnel" to { tr("Туннель", "Tunnel", "Тунель") },
    "providers" to { tr("Настройки провайдеров", "Provider settings", "Налаштування провайдерів") },
    "ping" to { tr("Настройки пинга", "Ping settings", "Налаштування пінгу") },
    "about" to { tr("О приложении", "About", "Про застосунок") },
    "stats" to { tr("Статистика и скорость", "Statistics and speed", "Статистика і швидкість") },
    "netlog" to { tr("Журнал сети", "Network log", "Журнал мережі") },
    "schemes" to { tr("Схемы URL-адресов", "URL schemes", "Схеми URL-адрес") },
    "backup" to { tr("Резервное копирование", "Backup", "Резервне копіювання") },
    "logs" to { tr("Журналы туннеля", "Tunnel logs", "Журнали тунелю") },
)

@Composable
private fun SettingsMenu(store: Store, open: (String?) -> Unit, refresh: () -> Unit) {
    val context = LocalContext.current
    val s = store.settings
    var resetting by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        run { Text(tr("Настройки", "Settings", "Налаштування"), Modifier.padding(top = 12.dp), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
        run { Banner("app-settings", tr("Всё под вашим контролем", "Everything under your control", "Усе під вашим контролем"),
            tr("Каждая настройка — здесь, в меню", "Every setting is here in the menu", "Кожне налаштування — тут, у меню")) }
        run { Section(tr("Прокси по приложениям", "Per-app proxy", "Проксі за застосунками")) {
            NavRow(Icons.Filled.Apps, tr("Прокси по приложениям", "Per-app proxy", "Проксі за застосунками"), when (s.appsMode) {
                "only" -> tr("Только выбранные", "Only selected", "Лише вибрані") + " (${s.apps.size})"
                "except" -> tr("Кроме выбранных", "Except selected", "Крім вибраних") + " (${s.apps.size})"
                else -> tr("Выкл", "Off", "Вимк") }) { open("apps") }
        } }
        run { Section(tr("Оформление", "Appearance", "Оформлення")) {
            NavRow(Icons.Filled.Palette, tr("Оформление", "Appearance", "Оформлення"), themeName(s.theme)) { open("appearance") }
        } }
        run { Section(tr("Соединение и туннель", "Connection and tunnel", "З'єднання і тунель")) {
            NavRow(Icons.Filled.Bolt, tr("Соединение", "Connection", "З'єднання"), tr("Настроить", "Configure", "Налаштувати")) { open("connection") }
            NavRow(Icons.Filled.Layers, tr("Туннель", "Tunnel", "Тунель"), tr("Настроить", "Configure", "Налаштувати")) { open("tunnel") }
            NavRow(Icons.Filled.Route, tr("Маршрутизация", "Routing", "Маршрутизація"), routingName(s.routing)) { open("routing") }
        } }
        run { Section(tr("Провайдеры", "Providers", "Провайдери")) {
            NavRow(Icons.Filled.Settings, tr("Настройки провайдеров", "Provider settings", "Налаштування провайдерів"),
                if (s.autoUpdate) tr("Авто", "Auto", "Авто") else tr("Вручную", "Manual", "Вручну")) { open("providers") }
            NavRow(Icons.Filled.Speed, tr("Настройки пинга", "Ping settings", "Налаштування пінгу"), pingMethodName(s.pingMethod)) { open("ping") }
        } }
        run { Section(tr("Приложение", "App", "Застосунок")) {
            NavRow(Icons.Filled.Info, tr("О приложении", "About", "Про застосунок"), "v${BuildConfig.VERSION_NAME}") { open("about") }
            NavRow(Icons.Filled.Speed, tr("Статистика и скорость", "Statistics and speed", "Статистика і швидкість")) { open("stats") }
            NavRow(Icons.Filled.Terminal, tr("Журнал сети", "Network log", "Журнал мережі"),
                if (s.networkLog) tr("Включён", "On", "Увімкнено") else tr("Выключен", "Off", "Вимкнено")) { open("netlog") }
            NavRow(Icons.Filled.Link, tr("Схемы URL-адресов", "URL schemes", "Схеми URL-адрес"), "corgi://") { open("schemes") }
            NavRow(Icons.Filled.CloudUpload, tr("Резервное копирование", "Backup", "Резервне копіювання")) { open("backup") }
        } }
        run { Section(tr("Отладка", "Debugging", "Налагодження")) {
            NavRow(Icons.Filled.Terminal, tr("Журналы туннеля", "Tunnel logs", "Журнали тунелю"),
                (if (s.logLevel == "none") tr("Выключены", "Off", "Вимкнено") else s.logLevel) + " · " + if (s.logHours == 0) "∞" else "${s.logHours} " + tr("ч", "h", "год")) { open("logs") }
        } }
        run {
            OutlinedButton(onClick = { resetting = true }, Modifier.fillMaxWidth().padding(vertical = 12.dp).testTag("reset"),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
                Text(tr("Сбросить настройки", "Reset settings", "Скинути налаштування"))
            }
        }
    }
    if (resetting) AlertDialog(onDismissRequest = { resetting = false },
        title = { Text(tr("Сбросить настройки?", "Reset settings?", "Скинути налаштування?")) },
        text = { Text(tr("Все настройки вернутся к начальным. Подписки и серверы останутся.", "All settings go back to defaults. Subscriptions and servers stay.",
            "Усі налаштування повернуться до початкових. Підписки й сервери залишаться.")) },
        confirmButton = { Button(onClick = { store.resetSettings(); I18n.apply("system"); AppIcons.apply(context, "corgi"); resetting = false; UpdateJob.schedule(context); (context as? Activity)?.recreate() ?: refresh() }) {
            Text(tr("Сбросить", "Reset", "Скинути")) } },
        dismissButton = { TextButton(onClick = { resetting = false }) { Text(tr("Отмена", "Cancel", "Скасувати")) } })
}

private fun themeName(t: String) = when (t) { "system" -> tr("Авто", "Auto", "Авто"); "light" -> tr("Светлая", "Light", "Світла")
    "dark" -> tr("Тёмная", "Dark", "Темна"); else -> tr("Корги", "Corgi", "Коргі") }

private fun routingName(r: String) = when (r) { "global" -> tr("Всё через VPN", "Everything", "Усе через VPN")
    "bypass_ru" -> tr("РФ напрямую", "Russia direct", "РФ напряму"); "custom" -> tr("Свои правила", "Own rules", "Власні правила")
    else -> tr("Кроме локальной сети", "All but LAN", "Крім локальної мережі") }

private fun pingMethodName(m: String) = when (m) { "tcp" -> "TCP"; "icmp" -> "ICMP"; else -> tr("Через ядро", "Via core", "Через ядро") }

// ---------------------------------------------------------------- pages

@Composable
private fun AppsPage(store: Store, s: Settings, save: (Settings) -> Unit) {
    // v1.6.0 (N10): «Прокси по приложениям» — a whole screen with icons, search, system apps, import and export.
    val context = LocalContext.current
    val clipboard = context.getSystemService(android.content.ClipboardManager::class.java)
    AppsScreen(s, save,
        share = { text -> clipboard?.setPrimaryClip(android.content.ClipData.newPlainText("apps", text))
            context.startActivity(android.content.Intent.createChooser(android.content.Intent(android.content.Intent.ACTION_SEND).setType("application/json")
                .putExtra(android.content.Intent.EXTRA_TEXT, text), null)) },
        paste = { clipboard?.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString() })
}

@Composable
private fun AppearancePage(s: Settings, save: (Settings) -> Unit) {
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Тема", "Theme", "Тема")) {
            listOf("corgi" to (tr("Корги", "Corgi", "Коргі") to tr("Ночь и оранжевый корги — фирменная", "Night and corgi orange — the brand", "Ніч і помаранчевий коргі — фірмова")),
                "system" to (tr("Авто", "Auto", "Авто") to tr("Следует за системной темой", "Follows the system theme", "Слідує за системною темою")),
                "light" to (tr("Светлая", "Light", "Світла") to tr("Светлый фон, оранжевый акцент", "Light background, orange accent", "Світле тло, помаранчевий акцент")),
                "dark" to (tr("Тёмная", "Dark", "Темна") to tr("Нейтральная тёмная", "Neutral dark", "Нейтральна темна"))).forEach { (key, text) ->
                ServerRow(text.first, text.second, s.theme == key) { save(s.copy(theme = key)) }
            }
        }
        Section(tr("Дополнительно", "More", "Додатково")) {
            if (Build.VERSION.SDK_INT >= 31) ToggleRow("Material You", tr("Цвета обоев системы", "System wallpaper colours", "Кольори шпалер системи"), s.materialYou) {
                save(s.copy(materialYou = it)) }
            ToggleRow(tr("AMOLED чёрный", "AMOLED black", "AMOLED чорний"), tr("Чисто чёрный фон — экономит заряд на OLED", "Pure black — saves battery on OLED",
                "Чисто чорне тло — економить заряд на OLED"), s.amoled) { save(s.copy(amoled = it)) }
            ToggleRow(tr("Вибрация", "Vibration", "Вібрація"), tr("Виброотклик при нажатиях", "Haptic feedback on taps", "Вібровідгук при натисканнях"), s.vibration) {
                save(s.copy(vibration = it)) }
        }
        Section(tr("Размер текста", "Text size", "Розмір тексту")) {
            Column(Modifier.padding(horizontal = 14.dp, vertical = 8.dp)) {
                Text(tr("Съешь ещё этих мягких французских булок", "The quick brown corgi jumps over the lazy dog", "Ще коргі грає з м'ячиком у саду"))
                var scale by remember { mutableStateOf(s.textScale) }
                Slider(value = scale, onValueChange = { scale = it }, valueRange = 0.8f..1.4f, steps = 11, onValueChangeFinished = { save(s.copy(textScale = scale)) },
                    modifier = Modifier.testTag("text-scale"))
                Text("${(scale * 100).toInt()} %", style = MaterialTheme.typography.bodySmall)
            }
        }
        Section(tr("Стиль подключения", "Connect style", "Стиль підключення")) {
            ChoiceRow(tr("Главный экран", "Home screen", "Головний екран"), "", listOf("classic" to tr("Классический", "Classic", "Класичний"),
                "compact" to tr("Компактный", "Compact", "Компактний")), s.connectStyle) { save(s.copy(connectStyle = it)) }
        }
        Section(tr("Иконка приложения", "App icon", "Іконка застосунку")) {
            Row(Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                listOf(Triple("corgi", R.mipmap.ic_launcher, tr("Корги", "Corgi", "Коргі")), Triple("night", R.mipmap.ic_launcher_night, tr("Ночь", "Night", "Ніч")),
                    Triple("mint", R.mipmap.ic_launcher_mint, tr("Мята", "Mint", "М'ята"))).forEach { (key, icon, label) ->
                    Column(Modifier.clickable { save(s.copy(appIcon = key)); AppIcons.apply(context, key) }.testTag("icon-$key"),
                        horizontalAlignment = Alignment.CenterHorizontally) {
                        androidx.compose.foundation.Image(androidx.compose.ui.res.painterResource(icon), label,
                            Modifier.size(56.dp).then(if (s.appIcon == key) Modifier.border(2.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(14.dp)) else Modifier))
                        Text(label, style = MaterialTheme.typography.bodySmall, color = if (s.appIcon == key) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            Text(tr("Значок на рабочем столе обновится через несколько секунд.", "The home screen icon updates in a few seconds.", "Значок на робочому столі оновиться за кілька секунд."),
                Modifier.padding(horizontal = 14.dp, vertical = 4.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Section(tr("Язык", "Language", "Мова")) {
            ChoiceRow(tr("Язык приложения", "App language", "Мова застосунку"), "", listOf("system" to tr("Как в системе", "System", "Як у системі"),
                "ru" to "Русский", "en" to "English", "uk" to "Українська"), s.lang) {
                save(s.copy(lang = it)); I18n.apply(it); (context as? Activity)?.recreate()
            }
        }
    }
}

@Composable
private fun ConnectionPage(s: Settings, save: (Settings) -> Unit) {
    val context = LocalContext.current
    val tileName = androidx.compose.ui.res.stringResource(R.string.app_short)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Плитка в шторке", "Quick settings tile", "Плитка в шторці")) {
            NavRow(Icons.Filled.Bolt, tr("Добавить плитку в шторку", "Add the tile to quick settings", "Додати плитку в шторку"),
                hint = tr("Подключение и отключение без открытия приложения", "Connect and disconnect without opening the app", "Підключення без відкриття застосунку")) {
                if (Build.VERSION.SDK_INT >= 33) context.getSystemService(StatusBarManager::class.java)?.requestAddTileService(
                    ComponentName(context, QuickTile::class.java), tileName, AndroidIcon.createWithResource(context, R.drawable.corgi_logo),
                    context.mainExecutor) { }
                else context.startActivity(Intent(AndroidSettings.ACTION_SETTINGS))
            }
        }
        Section(tr("Автоподключение", "Auto connect", "Автопідключення")) {
            ToggleRow(tr("Подключаться при запуске приложения", "Connect when the app opens", "Підключатися під час запуску"), "", s.autoConnectLaunch) {
                save(s.copy(autoConnectLaunch = it)) }
            ToggleRow(tr("Подключаться при загрузке устройства", "Connect when the device starts", "Підключатися під час завантаження пристрою"),
                tr("Нужно разрешение VPN, выданное раньше", "Needs the VPN permission granted before", "Потрібен раніше наданий дозвіл VPN"), s.autoConnectBoot) {
                save(s.copy(autoConnectBoot = it)) }
            // v1.6.0 (N10)
            ToggleRow(tr("Подключаться при смене сети", "Connect when the network changes", "Підключатися при зміні мережі"),
                tr("Wi-Fi ↔ мобильная сеть; Android может не разрешить запуск в фоне", "Wi-Fi ↔ mobile; Android may not allow a background start",
                    "Wi-Fi ↔ мобільна мережа; Android може не дозволити запуск у фоні"), s.autoConnectNetwork) {
                save(s.copy(autoConnectNetwork = it)); shop.corgi.client.vpn.NetworkReceiver.sync(context) }
            ToggleRow(tr("Сервер и статус на плитке", "Server and state on the tile", "Сервер і статус на плитці"),
                tr("Выключите, чтобы оставить только название", "Turn off to keep only the name", "Вимкніть, щоб лишити тільки назву"), s.tileDetails) {
                save(s.copy(tileDetails = it)); QuickTile.refresh(context) }
        }
        TrustedWifiSection(s, save)
        Section("Kill Switch") {
            NavRow(Icons.Filled.Settings, tr("Блокировать интернет без VPN", "Block internet without the VPN", "Блокувати інтернет без VPN"),
                hint = tr("Android делает это сам: «Постоянная VPN» и «Блокировать соединения без VPN» в настройках VPN системы.",
                    "Android does it itself: «Always-on VPN» and «Block connections without VPN» in the system VPN settings.",
                    "Android робить це сам: «Постійна VPN» і «Блокувати з'єднання без VPN» у системних налаштуваннях VPN.")) {
                context.startActivity(Intent(AndroidSettings.ACTION_VPN_SETTINGS))
            }
        }
        Section(tr("Локальная сеть", "Local network", "Локальна мережа")) {
            ToggleRow(tr("Разрешить LAN подключения", "Allow LAN connections", "Дозволити LAN з'єднання"),
                tr("Локальная сеть (роутер, принтер, ТВ) — мимо туннеля", "The local network (router, printer, TV) bypasses the tunnel",
                    "Локальна мережа (роутер, принтер, ТБ) — повз тунель"), s.routing != "global") {
                save(s.copy(routing = if (it) (if (s.routing == "global") "bypass_lan" else s.routing) else "global"))
            }
            ToggleRow("IPv6", tr("Адреса IPv6 через туннель", "IPv6 through the tunnel", "Адреси IPv6 через тунель"), s.ipv6) { save(s.copy(ipv6 = it)) }
        }
    }
}

@Composable
private fun TunnelPage(store: Store, s: Settings, save: (Settings) -> Unit) {
    var length by remember { mutableStateOf(s.fragmentLength) }
    var interval by remember { mutableStateOf(s.fragmentInterval) }
    var dns by remember { mutableStateOf(s.dns.joinToString(", ")) }
    var localDns by remember { mutableStateOf(s.localDns) }
    var mtu by remember { mutableStateOf(s.mtu.toString()) }
    var routes by remember { mutableStateOf(s.excludedRoutes.joinToString("\n")) }
    var message by remember { mutableStateOf("") }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Режим туннеля", "Tunnel mode", "Режим тунелю")) {
            ChoiceRow(tr("Режим", "Mode", "Режим"), if (s.tunnelMode == "proxy") tr("Только локальный прокси, без VPN и значка ключа: Android не пустит через него приложения без настройки прокси",
                "Only the local proxy, no VPN and no key icon: apps without a proxy setting go direct", "Лише локальний проксі, без VPN і значка ключа: застосунки без налаштування проксі йдуть напряму")
                else tr("Весь трафик устройства через туннель", "All device traffic through the tunnel", "Увесь трафік пристрою через тунель"),
                listOf("tun" to "TUN", "proxy" to tr("Только прокси", "Proxy only", "Лише проксі")), s.tunnelMode) { save(s.copy(tunnelMode = it)) }
            ToggleRow(tr("Скорость в уведомлении", "Speed in the notification", "Швидкість у сповіщенні"), tr("Загрузка и отдача каждую секунду", "Download and upload every second",
                "Завантаження й віддача щосекунди"), s.speedNotification) { save(s.copy(speedNotification = it)) }
            ToggleRow(tr("Держать устройство активным", "Keep the device awake", "Тримати пристрій активним"), tr("Wakelock во время работы — нужен на Xiaomi/HyperOS; разряжает батарею быстрее",
                "A wake lock while connected — needed on Xiaomi/HyperOS; drains the battery faster", "Wakelock під час роботи — потрібен на Xiaomi/HyperOS; швидше розряджає батарею"),
                s.wakelock) { save(s.copy(wakelock = it)) }
            ToggleRow(tr("Мультиплексирование (Mux)", "Multiplexing (Mux)", "Мультиплексування (Mux)"), tr("Объединять соединения в один канал (не для XTLS Vision и Hysteria2)",
                "Combine connections into one channel (not for XTLS Vision or Hysteria2)", "Об'єднувати з'єднання в один канал (не для XTLS Vision і Hysteria2)"), s.mux) { save(s.copy(mux = it)) }
        }
        // v1.7.1 (N12): Smart Failover — leave a dead server by itself.
        Section(tr("Авто-переключение", "Smart Failover", "Авто-перемикання")) {
            ToggleRow(tr("Переключаться при обрыве", "Switch when the server dies", "Перемикатися при обриві"),
                tr("Раз в 10 с проверяется «URL проверки» через туннель; нет ответа дольше заданного — подключение к самому быстрому другому серверу провайдера. Для «Автовыбора» не нужно",
                    "Every 10 s the check URL is opened through the tunnel; no answer for longer than set — the fastest other server of the provider. Not needed for «Auto select»",
                    "Раз на 10 с перевіряється URL через тунель; немає відповіді довше заданого — найшвидший інший сервер провайдера"),
                s.smartFailover) { save(s.copy(smartFailover = it)) }
            if (s.smartFailover) ChoiceRow(tr("Ждать ответа", "Wait for an answer", "Чекати відповіді"), "",
                listOf(15, 30, 60, 120).map { it.toString() to "$it " + tr("с", "s", "с") }, s.failoverSeconds.toString()) { save(s.copy(failoverSeconds = it.toInt())) }
        }
        ProxySection(store, s, save)
        Section(tr("Фрагментирование", "Fragmentation", "Фрагментування")) {
            ToggleRow(tr("Фрагментирование", "Fragmentation", "Фрагментування"), tr("Обход DPI: TLS-приветствие по кусочкам (для TLS-серверов; REALITY не затрагивает)",
                "DPI bypass: the TLS hello in pieces (TLS servers; REALITY is not affected)", "Обхід DPI: TLS-привітання частинами (для TLS-серверів; REALITY не зачіпає)"),
                s.fragment) { save(s.copy(fragment = it)) }
            if (s.fragment) {
                ChoiceRow("Packets", "", Settings.FRAGMENT_PACKETS.map { it to it }, s.fragmentPackets) { save(s.copy(fragmentPackets = it)) }
                ToggleRow("Noises", tr("Случайные пакеты перед данными", "Random packets before the data", "Випадкові пакети перед даними"), s.noises) { save(s.copy(noises = it)) }
                Row(Modifier.padding(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(length, { length = it }, Modifier.weight(1f), label = { Text("Length") }, singleLine = true)
                    OutlinedTextField(interval, { interval = it }, Modifier.weight(1f), label = { Text("Interval") }, singleLine = true)
                }
                TextButton(onClick = { message = runCatching { save(s.copy(fragmentLength = length.trim(), fragmentInterval = interval.trim())) }
                    .fold({ tr("Сохранено", "Saved", "Збережено") }, { tr("Формат: 100-200", "Format: 100-200", "Формат: 100-200") }) },
                    Modifier.padding(start = 6.dp)) { Text(tr("Сохранить", "Save", "Зберегти")) }
            }
        }
        Section(tr("Трафик", "Traffic", "Трафік")) {
            ToggleRow(tr("Анализ трафика (sniffing)", "Traffic sniffing", "Аналіз трафіку (sniffing)"), tr("Определять домены по TLS/HTTP/QUIC для правил", "Detect domains from TLS/HTTP/QUIC for the rules",
                "Визначати домени за TLS/HTTP/QUIC для правил"), s.sniffing) { save(s.copy(sniffing = it)) }
            if (s.sniffing) ToggleRow(tr("Маршрутизация по домену (routeOnly)", "Route by domain (routeOnly)", "Маршрутизація за доменом (routeOnly)"),
                tr("Домен из сниффинга — только для выбора маршрута, адрес соединения не подменяется", "The sniffed domain only picks the route; the destination is kept",
                    "Домен зі сніфінгу — лише для вибору маршруту, адресу не підмінено"), s.routeOnly) { save(s.copy(routeOnly = it)) }
            ToggleRow(tr("Блокировать UDP", "Block UDP", "Блокувати UDP"), tr("Сломает QUIC, звонки и игры; DNS работает. Включайте, только если знаете зачем",
                "Breaks QUIC, calls and games; DNS still works. Only if you know why", "Зламає QUIC, дзвінки та ігри; DNS працює. Лише якщо знаєте навіщо"), s.blockUdp) {
                save(s.copy(blockUdp = it)) }
            ChoiceRow(tr("Таймаут простоя", "Idle timeout", "Таймаут простою"), tr("Через сколько секунд закрывать неактивные соединения", "Seconds before idle connections close",
                "Через скільки секунд закривати неактивні з'єднання"), listOf(60, 120, 300, 600, 1800).map { it.toString() to "$it" }, s.idleTimeout.toString()) {
                save(s.copy(idleTimeout = it.toInt())) }
        }
        Section("DNS · MTU") {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(dns, { dns = it }, Modifier.fillMaxWidth(), label = { Text("DNS (1.1.1.1, https://dns.google/dns-query)") })
                OutlinedTextField(localDns, { localDns = it }, Modifier.fillMaxWidth().testTag("local-dns"), singleLine = true,
                    label = { Text(tr("Локальный DNS для сайтов напрямую", "Local DNS for direct sites", "Локальний DNS для сайтів напряму")) },
                    placeholder = { Text("77.88.8.8 · https+local://dns.yandex/dns-query") })
                OutlinedTextField(mtu, { mtu = it }, Modifier.fillMaxWidth(), label = { Text("MTU (1280–9000)") }, singleLine = true)
                Button(onClick = {
                    message = runCatching {
                        val list = dns.split(",", " ", "\n").map { it.trim() }.filter { it.isNotBlank() }.take(4)
                        require(list.isNotEmpty() && list.all { Regex("^(https://[^\\s]+|tls://[^\\s]+|[0-9a-fA-F:.]+)$").matches(it) })
                        require(localDns.isBlank() || Settings.DNS_ADDRESS.matches(localDns.trim()))
                        save(s.copy(dns = list, mtu = mtu.trim().toInt(), localDns = localDns.trim()))
                    }.fold({ tr("Сохранено", "Saved", "Збережено") }, { tr("Проверьте DNS и MTU", "Check DNS and MTU", "Перевірте DNS і MTU") })
                }) { Text(tr("Сохранить", "Save", "Зберегти")) }
            }
            // v1.7.0 (N12): local DNS for the direct domains, FakeDNS and how routing resolves domains.
            ToggleRow("FakeDNS", tr("Приложения сразу получают адрес из 198.18.0.0/15, настоящий запрос делает сервер — быстрее открываются сайты и нет утечек DNS",
                "Apps get an address from 198.18.0.0/15 at once, the server does the real lookup — faster first loads, no DNS leaks",
                "Застосунки одразу отримують адресу з 198.18.0.0/15, справжній запит робить сервер"), s.fakeDns) { save(s.copy(fakeDns = it)) }
            ChoiceRow(tr("Стратегия доменов", "Domain strategy", "Стратегія доменів"),
                tr("Как правила сравнивают домены с IP: «Авто» — IPIfNonMatch с geo-файлами", "How rules match domains against IPs: «Auto» — IPIfNonMatch with geo files",
                    "Як правила зіставляють домени з IP: «Авто» — IPIfNonMatch з geo-файлами"),
                Settings.DOMAIN_STRATEGIES.map { it to if (it == "auto") tr("Авто", "Auto", "Авто") else it }, s.domainStrategy) { save(s.copy(domainStrategy = it)) }
        }
        Section(tr("Исключённые маршруты", "Excluded routes", "Виключені маршрути")) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(tr("Диапазоны IP (CIDR), которые идут мимо туннеля, по одному в строке", "IP ranges (CIDR) that bypass the tunnel, one per line",
                    "Діапазони IP (CIDR) повз тунель, по одному в рядку"), style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(routes, { routes = it }, Modifier.fillMaxWidth().testTag("excluded"), placeholder = { Text("203.0.113.0/24") })
                Button(onClick = {
                    message = runCatching { save(s.copy(excludedRoutes = routes.lines().map { it.trim() }.filter { it.isNotBlank() }.distinct().take(64))) }
                        .fold({ tr("Сохранено", "Saved", "Збережено") }, { tr("Неверный диапазон: нужен вид 10.0.0.0/8", "Invalid range: use 10.0.0.0/8", "Невірний діапазон: потрібно 10.0.0.0/8") })
                }) { Text(tr("Сохранить", "Save", "Зберегти")) }
            }
        }
        if (message.isNotBlank()) Text(message, color = MaterialTheme.colorScheme.primary)
        Text(tr("Изменения туннеля применяются при следующем подключении.", "Tunnel changes apply on the next connection.", "Зміни тунелю діють з наступного підключення."),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ProvidersPage(s: Settings, save: (Settings) -> Unit) {
    var agent by remember { mutableStateOf(s.userAgent) }
    var message by remember { mutableStateOf("") }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Обновлять", "Update", "Оновлювати")) {
            ToggleRow(tr("Автообновление", "Auto update", "Автооновлення"), tr("Обновлять подписки в фоне", "Update subscriptions in the background", "Оновлювати підписки у фоні"),
                s.autoUpdate) { save(s.copy(autoUpdate = it)) }
            if (s.autoUpdate) ChoiceRow(tr("Интервал обновления", "Update interval", "Інтервал оновлення"), tr("Если подписка просит чаще — обновляется по её интервалу",
                "If the subscription asks for more often, its interval wins", "Якщо підписка просить частіше — за її інтервалом"),
                Settings.UPDATE_MINUTES.map { it.toString() to if (it < 60) "$it " + tr("мин", "min", "хв") else "${it / 60} " + tr("ч", "h", "год") }, s.updateMinutes.toString()) {
                save(s.copy(updateMinutes = it.toInt())) }
            ToggleRow(tr("Уведомлять об обновлениях", "Notify about updates", "Сповіщати про оновлення"), tr("Уведомление, когда подписки обновились в фоне",
                "A notification when subscriptions update in the background", "Сповіщення, коли підписки оновилися у фоні"), s.notifyUpdates) { save(s.copy(notifyUpdates = it)) }
        }
        Section(tr("При запуске", "On launch", "Під час запуску")) {
            ToggleRow(tr("Обновлять при запуске", "Update on launch", "Оновлювати під час запуску"), tr("Обновлять провайдеров при открытии приложения",
                "Update providers when the app opens", "Оновлювати провайдерів під час відкриття"), s.updateOnLaunch) { save(s.copy(updateOnLaunch = it)) }
            ToggleRow(tr("Пинг при запуске", "Ping on launch", "Пінг під час запуску"), tr("Проверять задержку серверов при открытии", "Test server delays when the app opens",
                "Перевіряти затримку серверів під час відкриття"), s.pingOnLaunch) { save(s.copy(pingOnLaunch = it)) }
            ToggleRow(tr("Пинг при обновлении", "Ping after update", "Пінг після оновлення"), tr("Проверять задержку после обновления провайдеров",
                "Test delays after providers update", "Перевіряти затримку після оновлення провайдерів"), s.pingAfterUpdate) { save(s.copy(pingAfterUpdate = it)) }
        }
        Section(tr("Сеть", "Network", "Мережа")) {
            ToggleRow(tr("Отправлять HWID", "Send HWID", "Надсилати HWID"), tr("Идентификатор устройства при обновлении (лимит устройств в панели)",
                "The device id on update (the panel's device limit)", "Ідентифікатор пристрою під час оновлення (ліміт пристроїв у панелі)"), s.sendHwid) { save(s.copy(sendHwid = it)) }
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(agent, { agent = it }, Modifier.fillMaxWidth(), label = { Text("User-Agent") }, singleLine = true)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { message = runCatching { save(s.copy(userAgent = agent.trim())) }.fold({ tr("Сохранено", "Saved", "Збережено") }, { "User-Agent?" }) }) {
                        Text(tr("Сохранить", "Save", "Зберегти")) }
                    TextButton(onClick = { agent = Settings.DEFAULT_AGENT; save(s.copy(userAgent = Settings.DEFAULT_AGENT)) }) { Text(tr("По умолчанию", "Default", "За замовчуванням")) }
                }
            }
        }
        Section(tr("Список серверов", "Server list", "Список серверів")) {
            listOf("default" to tr("По умолчанию", "Default", "За замовчуванням"), "ping" to tr("По пингу", "By ping", "За пінгом"),
                "name" to tr("По имени", "By name", "За назвою")).forEach { (key, label) -> ServerRow(label, "", s.sort == key) { save(s.copy(sort = key)) } }
        }
        if (message.isNotBlank()) Text(message, color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun PingPage(s: Settings, save: (Settings) -> Unit) {
    var url by remember { mutableStateOf(s.pingUrl) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Протокол пинга", "Ping method", "Протокол пінгу")) {
            listOf("core" to (tr("Через ядро Xray", "Through the Xray core", "Через ядро Xray") to tr("HTTP-запрос через сервер — настоящая задержка", "An HTTP request through the server — the real delay", "HTTP-запит через сервер — справжня затримка")),
                "tcp" to ("TCP Connect" to tr("Подключение к порту сервера", "Connect to the server's port", "Підключення до порту сервера")),
                "icmp" to ("ICMP Ping" to tr("Системный ping адреса", "System ping of the address", "Системний ping адреси"))).forEach { (key, t) ->
                ServerRow(t.first, t.second, s.pingMethod == key) { save(s.copy(pingMethod = key)) }
            }
        }
        Section(tr("Отображение пинга", "Ping display", "Відображення пінгу")) {
            listOf("digits" to tr("Цифры (мс)", "Digits (ms)", "Цифри (мс)"), "bar" to tr("Шкала", "Bar", "Шкала"), "both" to tr("Шкала и цифры", "Bar and digits", "Шкала і цифри"),
                "dots" to tr("Точки", "Dots", "Крапки")).forEach { (key, label) -> ServerRow(label, "", s.pingDisplay == key) { save(s.copy(pingDisplay = key)) } }
        }
        if (s.pingMethod == "core") Section(tr("URL для теста", "Test URL", "URL для тесту")) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(), singleLine = true)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("Google", "Cloudflare", "Apple").zip(Settings.PING_URLS).forEach { (name, value) ->
                        androidx.compose.material3.FilterChip(selected = url == value, onClick = { url = value; save(s.copy(pingUrl = value)) }, label = { Text(name) })
                    }
                }
                Button(onClick = { runCatching { save(s.copy(pingUrl = url.trim())) } }) { Text(tr("Сохранить", "Save", "Зберегти")) }
            }
        }
        Section(tr("Таймаут", "Timeout", "Таймаут")) {
            ChoiceRow(tr("Сколько ждать ответа", "How long to wait", "Скільки чекати відповіді"), "", (1..10).map { it.toString() to "$it " + tr("сек", "s", "с") },
                s.pingTimeout.toString()) { save(s.copy(pingTimeout = it.toInt())) }
        }
    }
}

@Composable
private fun AboutPage(store: Store) {
    val context = LocalContext.current
    var updateText by remember { mutableStateOf("") }
    var licenses by remember { mutableStateOf(false) }
    val hwid = store.hwid
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Banner("app-info", tr("Корги Люси: клиент", "Corgi Lusi: client", "Коргі Люсі: клієнт"), "v${BuildConfig.VERSION_NAME}")
        Section(tr("Информация", "Information", "Інформація")) {
            InfoRow(tr("Версия Xray", "Xray version", "Версія Xray"), Xray.version().ifBlank { "—" })
            InfoRow(tr("Версия приложения", "App version", "Версія застосунку"), "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
            // v1.6.1 (N11): which AndroidLibXrayLite commit the core is built from and when updates were last checked.
            InfoRow(tr("Сборка ядра", "Core build", "Збірка ядра"), "AndroidLibXrayLite ${BuildConfig.XRAY_AAR_COMMIT.take(8)}")
            InfoRow(tr("Проверка обновлений", "Update check", "Перевірка оновлень"), formatStamp(store.updateCheckedAt()))
            InfoRow(tr("Geo-файлы", "Geo files", "Geo-файли"), formatStamp(store.geoUpdatedAt()))
        }
        Section(tr("Устройство", "Device", "Пристрій")) {
            InfoRow(tr("Версия ОС", "OS version", "Версія ОС"), "Android ${Build.VERSION.RELEASE}")
            InfoRow(tr("Модель", "Model", "Модель"), "${Build.MANUFACTURER} ${Build.MODEL}")
            Row(Modifier.fillMaxWidth().clickable {
                context.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("HWID", hwid))
                updateText = tr("HWID скопирован", "HWID copied", "HWID скопійовано")
            }.padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("HWID", Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
                Icon(Icons.Filled.ContentCopy, null, Modifier.padding(end = 6.dp))
                Text(hwid, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            }
        }
        // v1.6.1 (N11): the client and its Xray core update themselves; the geo files too.
        var s by remember { mutableStateOf(store.settings) }
        Section(tr("Обновления", "Updates", "Оновлення")) {
            ToggleRow(tr("Обновлять автоматически", "Update automatically", "Оновлювати автоматично"),
                tr("Раз в сутки по Wi-Fi: новая версия с новым ядром Xray скачивается и проверяется, установка — по нажатию",
                    "Once a day on Wi-Fi: a new version with a new Xray core is downloaded and checked, installed by a tap",
                    "Раз на добу через Wi-Fi: нова версія з новим ядром Xray завантажується й перевіряється"), s.autoUpdateApp) {
                s = s.copy(autoUpdateApp = it); store.settings = s; shop.corgi.client.vpn.AppUpdateJob.schedule(context) }
            ToggleRow(tr("Обновлять geo-файлы", "Update the geo files", "Оновлювати geo-файли"),
                tr("Раз в сутки, если они скачаны", "Once a day, when they are downloaded", "Раз на добу, якщо вони завантажені"), s.autoUpdateGeo) {
                s = s.copy(autoUpdateGeo = it); store.settings = s; shop.corgi.client.vpn.AppUpdateJob.schedule(context) }
            store.readyUpdate()?.let { apk ->
                NavRow(Icons.Filled.Settings, tr("Установить ", "Install ", "Встановити ") + (store.cachedUpdate()?.versionName ?: ""),
                    hint = tr("Скачано и проверено по SHA-256", "Downloaded and checked by SHA-256", "Завантажено й перевірено SHA-256")) {
                    (context as? android.app.Activity)?.let { runCatching { shop.corgi.client.vpn.ApkInstaller.install(it, apk) } }
                }
            }
        }
        Section(tr("Ссылки", "Links", "Посилання")) {
            NavRow(Icons.Filled.Info, tr("Лицензии третьих сторон", "Third-party licences", "Ліцензії третіх сторін")) { licenses = true }
            NavRow(Icons.Filled.Settings, tr("Проверить обновления", "Check for updates", "Перевірити оновлення")) {
                updateText = tr("Проверка…", "Checking…", "Перевірка…")
                thread {
                    val text = runCatching { store.checkUpdate(force = true)?.also { u -> runCatching { store.downloadUpdate(u) } } }.fold(
                        { it?.let { u -> tr("Доступна версия ", "Version available: ", "Доступна версія ") + u.versionName } ?: tr("Установлена последняя версия", "Up to date", "Встановлено останню версію") },
                        { tr("Не удалось проверить", "Could not check", "Не вдалося перевірити") })
                    android.os.Handler(context.mainLooper).post { updateText = text }
                }
            }
        }
        if (updateText.isNotBlank()) Text(updateText, color = MaterialTheme.colorScheme.primary)
        Text(tr("Это приложение — только инструмент для подключения к вашим серверам. Оно не собирает личные данные.",
            "This app is only a tool to connect to your servers. It collects no personal data.",
            "Цей застосунок — лише інструмент для підключення до ваших серверів. Він не збирає особисті дані."),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(8.dp))
    }
    if (licenses) AlertDialog(onDismissRequest = { licenses = false }, confirmButton = { TextButton(onClick = { licenses = false }) { Text("OK") } },
        title = { Text(tr("Лицензии", "Licences", "Ліцензії")) },
        text = { Text("Xray-core — MPL-2.0\nAndroidLibXrayLite (libv2ray) — LGPL-3.0\nZXing core — Apache-2.0\nJetpack Compose, AndroidX — Apache-2.0\n" +
            "Google code scanner (Play services) — Google APIs Terms\ngeoip.dat / geosite.dat (runetfreedom) — GPL-3.0, " +
            tr("скачиваются по вашему выбору", "downloaded by your choice", "завантажуються за вашим вибором")) })
}

@Composable
private fun InfoRow(title: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp)) {
        Text(title, Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
    }
}

/** A date and time in the device's locale, or «—» for 0. */
internal fun formatStamp(millis: Long): String = if (millis <= 0L) "—" else
    java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT).format(java.util.Date(millis))

/**
 * v1.7.2 (N12): «Доверенные Wi-Fi» — names of networks where the tunnel pauses; «Добавить текущую» asks for the location
 * permission Android requires for the Wi-Fi name. In the background Android gives the name only with «Разрешить всегда».
 */
@Composable
private fun TrustedWifiSection(s: Settings, save: (Settings) -> Unit) {
    val context = LocalContext.current
    var name by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    fun addCurrent() {
        val ssid = shop.corgi.client.vpn.NetworkReceiver.currentSsid(context)
        note = if (ssid == null) {
            tr("Не видно имени сети: подключитесь к Wi-Fi и включите геолокацию", "No network name: join a Wi-Fi and turn location on",
                "Не видно назви мережі: підключіться до Wi-Fi та увімкніть геолокацію")
        } else {
            runCatching { save(s.copy(trustedWifi = (s.trustedWifi + ssid).distinct())) }
                .fold({ tr("Добавлено: ", "Added: ", "Додано: ") + ssid }, { tr("Не больше 20 сетей", "At most 20 networks", "Не більше 20 мереж") })
        }
        shop.corgi.client.vpn.NetworkReceiver.sync(context)
    }
    val permission = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) addCurrent() else note = tr("Без доступа к геолокации Android не показывает имя Wi-Fi", "Without location Android hides the Wi-Fi name",
            "Без геолокації Android не показує назву Wi-Fi")
    }
    Section(tr("Доверенные Wi-Fi", "Trusted Wi-Fi", "Довірені Wi-Fi")) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(tr("В этих сетях VPN встаёт на паузу, в мобильной сети и любой другой Wi-Fi — сразу включается снова. Android отдаёт имя сети только с доступом к геолокации, в фоне — «Разрешить всегда»",
                "On these networks the VPN pauses; on mobile data or any other Wi-Fi it comes back at once. Android gives the network name only with location access, in the background — «Allow all the time»",
                "У цих мережах VPN на паузі; у мобільній мережі чи іншому Wi-Fi — одразу вмикається знову. Назву мережі Android дає лише з доступом до геолокації"),
                style = MaterialTheme.typography.bodySmall)
            s.trustedWifi.forEach { ssid ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(ssid, Modifier.weight(1f).testTag("trusted-wifi"))
                    TextButton(onClick = { save(s.copy(trustedWifi = s.trustedWifi - ssid)); shop.corgi.client.vpn.NetworkReceiver.sync(context) }) { Text("✕") }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(name, { name = it.take(32) }, Modifier.weight(1f).testTag("trusted-name"), singleLine = true,
                    placeholder = { Text(tr("Имя сети (SSID)", "Network name (SSID)", "Назва мережі (SSID)")) })
                Button(onClick = {
                    note = runCatching { save(s.copy(trustedWifi = (s.trustedWifi + name.trim()).distinct())); name = ""; shop.corgi.client.vpn.NetworkReceiver.sync(context) }
                        .fold({ tr("Добавлено", "Added", "Додано") }, { tr("Неверное имя или больше 20 сетей", "Invalid name or more than 20 networks", "Невірна назва або понад 20 мереж") })
                }, modifier = Modifier.testTag("trusted-add")) { Text(tr("Добавить", "Add", "Додати")) }
            }
            OutlinedButton(onClick = {
                if (context.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) ==
                    android.content.pm.PackageManager.PERMISSION_GRANTED) addCurrent() else permission.launch(android.Manifest.permission.ACCESS_FINE_LOCATION)
            }) { Text(tr("Добавить текущую сеть", "Add the current network", "Додати поточну мережу")) }
            if (note.isNotBlank()) Text(note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }
    }
}

/**
 * v1.7.3 (N12, phase 2): traffic by day — through the VPN and direct — for 7 or 30 days, and a speed test of the
 * server through the running tunnel.
 */
@Composable
private fun StatsPage(store: Store) {
    val context = LocalContext.current
    var days by remember { mutableStateOf(7) }
    var speed by remember { mutableStateOf("") }
    var testing by remember { mutableStateOf(false) }
    val series = remember(days) { shop.corgi.client.core.TrafficHistory.series(store.trafficHistory(), days, System.currentTimeMillis()) }
    val vpnColor = MaterialTheme.colorScheme.primary
    val directColor = MaterialTheme.colorScheme.tertiary
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Трафик", "Traffic", "Трафік")) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(7, 30).forEach { d ->
                        if (d == days) Button(onClick = {}) { Text("$d " + tr("дн.", "days", "дн.")) }
                        else OutlinedButton(onClick = { days = d }, modifier = Modifier.testTag("stats-$d")) { Text("$d " + tr("дн.", "days", "дн.")) }
                    }
                }
                val max = (series.maxOfOrNull { it.vpn + it.direct } ?: 0L).coerceAtLeast(1L)
                androidx.compose.foundation.Canvas(Modifier.fillMaxWidth().height(140.dp).testTag("traffic-chart")) {
                    val slot = size.width / series.size
                    series.forEachIndexed { i, d ->
                        val x = i * slot + slot * 0.15f
                        val w = slot * 0.7f
                        val hv = size.height * d.vpn / max
                        val hd = size.height * d.direct / max
                        drawRect(directColor, androidx.compose.ui.geometry.Offset(x, size.height - hd), androidx.compose.ui.geometry.Size(w, hd))
                        drawRect(vpnColor, androidx.compose.ui.geometry.Offset(x, size.height - hd - hv), androidx.compose.ui.geometry.Size(w, hv))
                    }
                }
                val vpn = series.sumOf { it.vpn }
                val direct = series.sumOf { it.direct }
                Text("● " + tr("Через VPN: ", "Through the VPN: ", "Через VPN: ") + shop.corgi.client.core.SubInfo.bytes(vpn), color = vpnColor)
                Text("● " + tr("Напрямую: ", "Direct: ", "Напряму: ") + shop.corgi.client.core.SubInfo.bytes(direct), color = directColor)
                Text(tr("Считается, пока включён туннель; «напрямую» — локальная сеть и правила «direct»",
                    "Counted while the tunnel is on; «direct» — the local network and «direct» rules",
                    "Рахується, поки увімкнено тунель; «напряму» — локальна мережа та правила «direct»"), style = MaterialTheme.typography.bodySmall)
            }
        }
        Section("Speedtest") {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(tr("Скачивание 10 МБ и отдача 3 МБ через туннель — настоящая скорость текущего сервера",
                    "A 10 MB download and a 3 MB upload through the tunnel — the real speed of the current server",
                    "Завантаження 10 МБ і віддача 3 МБ через тунель — справжня швидкість сервера"), style = MaterialTheme.typography.bodySmall)
                Button(enabled = !testing, onClick = {
                    val check = shop.corgi.client.vpn.ClientVpnService.ipCheck
                    if (check == null) {
                        speed = tr("Сначала подключитесь", "Connect first", "Спочатку підключіться")
                        return@Button
                    }
                    testing = true
                    speed = tr("Измеряю…", "Measuring…", "Вимірюю…")
                    val main = android.os.Handler(context.mainLooper)
                    thread {
                        val text = runCatching { shop.corgi.client.core.SpeedTest.run(check) }.fold(
                            { r -> "↓ %.1f  ↑ %.1f ".format(r.downMbps, r.upMbps) + tr("Мбит/с", "Mbit/s", "Мбіт/с") },
                            { tr("Сервер не ответил", "The server did not answer", "Сервер не відповів") })
                        main.post { speed = text; testing = false }
                    }
                }, modifier = Modifier.testTag("speedtest")) { Text(tr("Измерить скорость", "Measure the speed", "Виміряти швидкість")) }
                if (speed.isNotBlank()) Text(speed, style = MaterialTheme.typography.titleMedium, modifier = Modifier.testTag("speed-result"))
            }
        }
    }
}

/**
 * v1.7.4 (N12, phase 2): «Журнал сети» — every connection with its domain and route (through the VPN, direct,
 * blocked, DNS), newest first, refreshed every 2 s while the page is open. Written only while the switch is on;
 * starts afresh on every connection and never leaves the device.
 */
@Composable
private fun NetworkLogPage(store: Store, s: Settings, save: (Settings) -> Unit) {
    val context = LocalContext.current
    var route by remember { mutableStateOf<shop.corgi.client.core.NetworkLog.Route?>(null) }
    var query by remember { mutableStateOf("") }
    var lines by remember { mutableStateOf(emptyList<String>()) }
    // Real-time refresh with the main looper (not the Compose clock): stops when the page closes.
    androidx.compose.runtime.DisposableEffect(Unit) {
        val logs = shop.corgi.client.core.Logs(context.filesDir)
        val handler = android.os.Handler(context.mainLooper)
        val tick = object : Runnable {
            override fun run() {
                lines = runCatching { logs.lines(logs.access, limit = 2000) }.getOrDefault(emptyList())
                handler.postDelayed(this, 2000)
            }
        }
        tick.run()
        onDispose { handler.removeCallbacks(tick) }
    }
    val entries = shop.corgi.client.core.NetworkLog.entries(lines, route, query)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Журнал сети", "Network log", "Журнал мережі")) {
            ToggleRow(tr("Записывать соединения", "Record connections", "Записувати з'єднання"),
                tr("Домены и куда они пошли: через VPN, напрямую, заблокированы. Включается со следующего подключения; хранится только на телефоне",
                    "Domains and where they went: VPN, direct, blocked. From the next connection; stays on the phone",
                    "Домени й куди вони пішли: VPN, напряму, заблоковано. З наступного підключення; лише на телефоні"),
                s.networkLog) { save(s.copy(networkLog = it)) }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(null to tr("Все", "All", "Усі"), shop.corgi.client.core.NetworkLog.Route.PROXY to "VPN", shop.corgi.client.core.NetworkLog.Route.DIRECT to tr("Напрямую", "Direct", "Напряму"), shop.corgi.client.core.NetworkLog.Route.BLOCK to tr("Блок", "Blocked", "Блок"))
                .forEach { (value, label) ->
                    if (route == value) Button(onClick = {}) { Text(label) } else OutlinedButton(onClick = { route = value }) { Text(label) }
                }
        }
        OutlinedTextField(query, { query = it.take(60) }, Modifier.fillMaxWidth().testTag("netlog-search"), singleLine = true,
            placeholder = { Text(tr("Поиск домена", "Search a domain", "Пошук домену")) })
        if (entries.isEmpty()) {
            Text(if (s.networkLog) tr("Пока пусто — откройте что-нибудь в браузере", "Empty so far — open something in a browser", "Поки порожньо")
                else tr("Включите запись и переподключитесь", "Turn recording on and reconnect", "Увімкніть запис і перепідключіться"),
                style = MaterialTheme.typography.bodySmall)
        }
        entries.forEach { e ->
            val (mark, color) = when (e.route) {
                shop.corgi.client.core.NetworkLog.Route.PROXY -> "VPN" to MaterialTheme.colorScheme.primary
                shop.corgi.client.core.NetworkLog.Route.DIRECT -> tr("напрямую", "direct", "напряму") to MaterialTheme.colorScheme.tertiary
                shop.corgi.client.core.NetworkLog.Route.BLOCK -> tr("блок", "blocked", "блок") to MaterialTheme.colorScheme.error
                shop.corgi.client.core.NetworkLog.Route.DNS -> "DNS" to MaterialTheme.colorScheme.onSurfaceVariant
            }
            Row(Modifier.fillMaxWidth().testTag("netlog-entry"), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(e.time, style = MaterialTheme.typography.bodySmall)
                Text("${e.host}:${e.port}", Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                Text(mark, color = color, style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}
