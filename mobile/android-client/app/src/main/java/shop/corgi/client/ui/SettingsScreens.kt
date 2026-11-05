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
            else -> LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    when (page) {
                        "apps" -> AppsPage(store, s, save)
                        "appearance" -> AppearancePage(s, save)
                        "connection" -> ConnectionPage(s, save)
                        "tunnel" -> TunnelPage(store, s, save)
                        "schemes" -> SchemesPage()
                        "backup" -> BackupPage(store, refresh)
                        "logs" -> LogsPage(store, s, save)
                        "providers" -> ProvidersPage(s) { save(it); UpdateJob.schedule(context) }
                        "ping" -> PingPage(s, save)
                        "about" -> AboutPage(store)
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
    val context = LocalContext.current
    var picking by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Какие приложения идут через VPN", "Which apps go through the VPN", "Які застосунки йдуть через VPN")) {
            listOf("all" to tr("Все приложения", "All apps", "Усі застосунки"), "only" to tr("Только выбранные", "Only selected", "Лише вибрані"),
                "except" to tr("Все, кроме выбранных", "All but selected", "Усі, крім вибраних")).forEach { (key, label) ->
                ServerRow(label, "", s.appsMode == key) { save(s.copy(appsMode = key)) }
            }
        }
        if (s.appsMode != "all") Button(onClick = { picking = true }, Modifier.fillMaxWidth()) {
            Text(tr("Выбрать приложения", "Choose apps", "Вибрати застосунки") + " (${s.apps.size})")
        }
    }
    if (picking) AppsDialog(context, s.apps) { chosen -> if (chosen != null) save(s.copy(apps = chosen)); picking = false }
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
            ToggleRow(tr("Сервер и статус на плитке", "Server and state on the tile", "Сервер і статус на плитці"),
                tr("Выключите, чтобы оставить только название", "Turn off to keep only the name", "Вимкніть, щоб лишити тільки назву"), s.tileDetails) {
                save(s.copy(tileDetails = it)); QuickTile.refresh(context) }
        }
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
                OutlinedTextField(mtu, { mtu = it }, Modifier.fillMaxWidth(), label = { Text("MTU (1280–9000)") }, singleLine = true)
                Button(onClick = {
                    message = runCatching {
                        val list = dns.split(",", " ", "\n").map { it.trim() }.filter { it.isNotBlank() }.take(4)
                        require(list.isNotEmpty() && list.all { Regex("^(https://[^\\s]+|tls://[^\\s]+|[0-9a-fA-F:.]+)$").matches(it) })
                        save(s.copy(dns = list, mtu = mtu.trim().toInt()))
                    }.fold({ tr("Сохранено", "Saved", "Збережено") }, { tr("Проверьте DNS и MTU", "Check DNS and MTU", "Перевірте DNS і MTU") })
                }) { Text(tr("Сохранить", "Save", "Зберегти")) }
            }
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
        Section(tr("Ссылки", "Links", "Посилання")) {
            NavRow(Icons.Filled.Info, tr("Лицензии третьих сторон", "Third-party licences", "Ліцензії третіх сторін")) { licenses = true }
            NavRow(Icons.Filled.Settings, tr("Проверить обновления", "Check for updates", "Перевірити оновлення")) {
                updateText = tr("Проверка…", "Checking…", "Перевірка…")
                thread {
                    val text = runCatching { store.checkUpdate(force = true) }.fold(
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
