package shop.corgi.client.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import shop.corgi.client.core.Backup
import shop.corgi.client.core.Logs
import shop.corgi.client.core.Scheme
import shop.corgi.client.core.Settings
import shop.corgi.client.core.tr
import shop.corgi.client.data.Store
import java.io.File
import java.net.Inet4Address
import java.net.NetworkInterface

private fun copy(context: Context, label: String, text: String) {
    context.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText(label, text))
}

/** corgi://routing/… and corgi://restore/… wait here for the user's yes. */
@Composable
internal fun SchemeDialog(store: Store, scheme: Scheme, onDone: () -> Unit) {
    when (scheme) {
        is Scheme.Rules -> AlertDialog(onDismissRequest = onDone,
            title = { Text(tr("Добавить правила маршрутизации?", "Add routing rules?", "Додати правила маршрутизації?")) },
            text = { Column { scheme.rules.take(20).forEach { Text("${it.match} → ${it.action}", style = MaterialTheme.typography.bodySmall) }
                if (scheme.rules.size > 20) Text("… +${scheme.rules.size - 20}") } },
            confirmButton = { Button(onClick = {
                val s = store.settings
                store.settings = s.copy(rules = (s.rules + scheme.rules).distinct(), routing = if (scheme.apply) "custom" else s.routing)
                onDone()
            }) { Text(if (scheme.apply) tr("Добавить и применить", "Add and apply", "Додати й застосувати") else tr("Добавить", "Add", "Додати")) } },
            dismissButton = { TextButton(onClick = onDone) { Text(tr("Отмена", "Cancel", "Скасувати")) } })
        is Scheme.Restore -> RestoreDialog(store, runCatching { Backup.parse(scheme.link) }, onDone)
        else -> onDone()
    }
}

@Composable
internal fun RestoreDialog(store: Store, backup: Result<Backup>, onDone: () -> Unit) {
    val context = LocalContext.current
    AlertDialog(onDismissRequest = onDone, title = { Text(tr("Восстановить?", "Restore?", "Відновити?")) },
        text = {
            backup.fold({ b -> Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(tr("Будет восстановлено (текущие провайдеры и настройки заменятся):", "Will be restored (current providers and settings are replaced):",
                    "Буде відновлено (поточні провайдери й налаштування заміняться):"))
                b.summary().forEach { Text("• $it", style = MaterialTheme.typography.bodySmall) }
                Text(tr("Правил маршрутизации: ", "Routing rules: ", "Правил маршрутизації: ") + b.settings.rules.size, style = MaterialTheme.typography.bodySmall)
            } }, { Text(it.message ?: tr("Файл не читается", "The file cannot be read", "Файл не читається"), color = MaterialTheme.colorScheme.error) })
        },
        confirmButton = { if (backup.isSuccess) Button(onClick = {
            store.restore(backup.getOrThrow()); shop.corgi.client.vpn.UpdateJob.schedule(context); AppIcons.apply(context, store.settings.appIcon); onDone()
        }, Modifier.testTag("restore-confirm")) { Text(tr("Восстановить", "Restore", "Відновити")) } },
        dismissButton = { TextButton(onClick = onDone) { Text(tr("Отмена", "Cancel", "Скасувати")) } })
}

// ---------------------------------------------------------------- local proxy and hotspot

/** This phone's addresses in the local network (Wi-Fi, hotspot) for «доступ через хотспот». */
internal fun lanAddresses(): List<String> = runCatching {
    NetworkInterface.getNetworkInterfaces().toList().filter { it.isUp && !it.isLoopback }
        .flatMap { it.inetAddresses.toList() }.filterIsInstance<Inet4Address>().map { it.hostAddress.orEmpty() }.filter { it.isNotBlank() }
}.getOrDefault(emptyList())

@Composable
internal fun ProxySection(store: Store, s: Settings, save: (Settings) -> Unit) {
    val context = LocalContext.current
    var socks by remember { mutableStateOf(s.socksPort.toString()) }
    var http by remember { mutableStateOf(s.httpPort.toString()) }
    var message by remember { mutableStateOf("") }
    val address = if (s.shareLan) lanAddresses().firstOrNull() ?: "0.0.0.0" else "127.0.0.1"
    Section(tr("Локальный прокси", "Local proxy", "Локальний проксі")) {
        if (s.tunnelMode == "tun") ToggleRow(tr("SOCKS5 и HTTP на устройстве", "SOCKS5 and HTTP on the device", "SOCKS5 і HTTP на пристрої"),
            tr("Режим «TUN + прокси»: приложения с настройкой прокси тоже идут через сервер", "«TUN + proxy»: apps with a proxy setting use the server too",
                "Режим «TUN + проксі»: застосунки з налаштуванням проксі теж ідуть через сервер"), s.localProxy) { save(s.copy(localProxy = it)) }
        if (s.tunnelMode == "proxy" || s.localProxy) {
            ToggleRow(tr("Доступ через хотспот", "Hotspot access", "Доступ через хотспот"),
                tr("Прокси на 0.0.0.0: устройства в той же Wi-Fi или точке доступа используют телефон как прокси. Нужны логин и пароль.",
                    "The proxy on 0.0.0.0: devices on the same Wi-Fi or hotspot use the phone as a proxy. Login and password required.",
                    "Проксі на 0.0.0.0: пристрої в тій самій Wi-Fi або точці доступу використовують телефон як проксі. Потрібні логін і пароль."),
                s.shareLan) { save(s.copy(shareLan = it, proxyAuth = it || s.proxyAuth)) }
            ToggleRow(tr("SOCKS5 авторизация", "SOCKS5 authentication", "SOCKS5 авторизація"), tr("Защищает прокси от приложений, которые ищут открытые порты",
                "Protects the proxy from apps that scan for open ports", "Захищає проксі від застосунків, що шукають відкриті порти"), s.proxyAuth) {
                save(s.copy(proxyAuth = it, shareLan = s.shareLan && it)) }
            if (s.proxyAuth) {
                CopyRow(tr("Логин", "Login", "Логін"), s.proxyUser) { copy(context, "login", s.proxyUser) }
                CopyRow(tr("Пароль", "Password", "Пароль"), "••••••••••••") { copy(context, "password", s.proxyPass); message = tr("Пароль скопирован", "Password copied", "Пароль скопійовано") }
                ToggleRow(tr("HTTP-прокси авторизация", "HTTP proxy authentication", "HTTP-проксі авторизація"), tr("Тот же логин и пароль на HTTP-прокси",
                    "The same login and password on the HTTP proxy", "Той самий логін і пароль на HTTP-проксі"), s.httpAuth) { save(s.copy(httpAuth = it)) }
            }
            CopyRow(tr("Адрес", "Address", "Адреса"), address) { copy(context, "address", address) }
            Row(Modifier.padding(horizontal = 14.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(socks, { socks = it }, Modifier.weight(1f), label = { Text("SOCKS5") }, singleLine = true)
                OutlinedTextField(http, { http = it }, Modifier.weight(1f), label = { Text("HTTP") }, singleLine = true)
            }
            Row(Modifier.padding(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    message = runCatching { save(s.copy(socksPort = socks.trim().toInt(), httpPort = http.trim().toInt())) }
                        .fold({ tr("Сохранено", "Saved", "Збережено") }, { tr("Порты 1024–65535, разные", "Ports 1024–65535, different", "Порти 1024–65535, різні") })
                }) { Text(tr("Сохранить порты", "Save ports", "Зберегти порти")) }
                TextButton(onClick = { store.newProxyCredentials(); message = tr("Новые логин и пароль", "New login and password", "Нові логін і пароль"); save(store.settings) }) {
                    Text(tr("Сбросить логин/пароль", "Reset login/password", "Скинути логін/пароль")) }
            }
            if (message.isNotBlank()) Text(message, Modifier.padding(horizontal = 14.dp, vertical = 6.dp), color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun CopyRow(title: String, value: String, onCopy: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onCopy).padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
        Icon(Icons.Filled.ContentCopy, null, Modifier.padding(start = 8.dp))
    }
}

// ---------------------------------------------------------------- pages: URL schemes, backup, logs

@Composable
internal fun SchemesPage() {
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(tr("Для автоматизации через ярлыки, Tasker и другие приложения. Нажмите, чтобы скопировать. Импорт и правила подтверждаются в приложении.",
            "For automation with shortcuts, Tasker and other apps. Tap to copy. Imports and rules are confirmed in the app.",
            "Для автоматизації через ярлики, Tasker та інші застосунки. Натисніть, щоб скопіювати. Імпорт і правила підтверджуються в застосунку."),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        listOf(tr("Запустить туннель", "Start the tunnel", "Запустити тунель") to listOf("corgi://connect", "corgi://open"),
            tr("Остановить", "Stop", "Зупинити") to listOf("corgi://disconnect", "corgi://close"),
            tr("Переключить", "Toggle", "Перемкнути") to listOf("corgi://toggle"),
            tr("Добавить конфигурацию", "Add a configuration", "Додати конфігурацію") to listOf("corgi://import/{base64}", "corgi://add/{url}"),
            tr("Маршрутизация", "Routing", "Маршрутизація") to listOf("corgi://routing/add/{base64}", "corgi://routing/onadd/{base64}"),
            tr("Резервная копия", "Backup", "Резервна копія") to listOf("corgi://restore/{backup}")).forEach { (title, items) ->
            Section(title) { items.forEach { CopyRow("", it) { copy(context, "scheme", it) } } }
        }
    }
}

@Composable
internal fun BackupPage(store: Store, refresh: () -> Unit) {
    val context = LocalContext.current
    var message by remember { mutableStateOf("") }
    var qr by remember { mutableStateOf<String?>(null) }
    var restoring by remember { mutableStateOf<Result<Backup>?>(null) }
    val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        if (uri != null) message = runCatching {
            context.contentResolver.openOutputStream(uri)!!.use { it.write(store.backup().toJson().toString(2).toByteArray()) }
        }.fold({ tr("Сохранено", "Saved", "Збережено") }, { it.message ?: "error" })
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) restoring = runCatching { Backup.parse(context.contentResolver.openInputStream(uri)!!.use { it.readBytes().toString(Charsets.UTF_8) }) }
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Создать резервную копию", "Create a backup", "Створити резервну копію")) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(tr("Все провайдеры, серверы, правила маршрутизации и настройки в одном файле.", "All providers, servers, routing rules and settings in one file.",
                    "Усі провайдери, сервери, правила маршрутизації й налаштування в одному файлі."), style = MaterialTheme.typography.bodySmall)
                Button(onClick = { export.launch("corgi-client-backup.json") }, Modifier.fillMaxWidth().testTag("export")) { Text(tr("Экспортировать", "Export", "Експортувати")) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = {
                        val link = store.backup().link()
                        if (link.length <= 2900) qr = link else message = tr("Слишком большая для QR — используйте файл или ссылку", "Too large for a QR — use the file or the link",
                            "Завелика для QR — використайте файл або посилання")
                    }, Modifier.weight(1f)) { Text(tr("Показать QR", "Show QR", "Показати QR")) }
                    OutlinedButton(onClick = { copy(context, "backup", store.backup().link()); message = tr("Ссылка скопирована", "Link copied", "Посилання скопійовано") },
                        Modifier.weight(1f)) { Text(tr("Копировать ссылку", "Copy link", "Копіювати посилання")) }
                }
            }
        }
        Section(tr("Восстановить", "Restore", "Відновити")) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(tr("Выберите файл. Перед применением вы увидите, что будет восстановлено.", "Pick a file. You will see what comes back before anything changes.",
                    "Виберіть файл. Перед застосуванням ви побачите, що буде відновлено."), style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = { pick.launch(arrayOf("application/json", "text/plain", "*/*")) }, Modifier.fillMaxWidth()) { Text(tr("Выбрать файл", "Choose a file", "Вибрати файл")) }
                OutlinedButton(onClick = {
                    val clip = context.getSystemService(ClipboardManager::class.java)?.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()
                    restoring = runCatching { Backup.parse(clip) }
                }, Modifier.fillMaxWidth()) { Text(tr("Из ссылки в буфере обмена", "From a link in the clipboard", "З посилання в буфері обміну")) }
            }
        }
        Text(tr("В копии нет логина и пароля локального прокси — на новом устройстве они создаются заново.", "The backup has no login and password of the local proxy — the new device makes its own.",
            "У копії немає логіна й пароля локального проксі — на новому пристрої вони створюються заново."), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (message.isNotBlank()) Text(message, color = MaterialTheme.colorScheme.primary)
    }
    qr?.let { QrDialog(it) { qr = null } }
    restoring?.let { RestoreDialog(store, it) { restoring = null; refresh() } }
}

@Composable
internal fun LogsPage(store: Store, s: Settings, save: (Settings) -> Unit) {
    val context = LocalContext.current
    val logs = remember { Logs(context.filesDir) }
    var revision by remember { mutableIntStateOf(0) }
    val files = remember(revision) { logs.files() }
    var chosen by remember { mutableStateOf(files.firstOrNull()?.name) }
    var query by remember { mutableStateOf("") }
    var level by remember { mutableStateOf("all") }
    val file = files.firstOrNull { it.name == chosen } ?: files.firstOrNull()
    val lines = remember(file, query, level, revision) { file?.let { logs.lines(it, query) }?.filter { Logs.matches(it, level) } ?: emptyList() }
    // v1.8.0 (N12): «Экспорт в .zip» — every log in one archive where the user chooses to save it.
    var zipNote by remember { mutableStateOf("") }
    val saveZip = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        zipNote = runCatching {
            context.contentResolver.openOutputStream(uri)!!.use { out ->
                val about = "Corgi Lusi client ${shop.corgi.client.BuildConfig.VERSION_NAME} (${shop.corgi.client.BuildConfig.VERSION_CODE})\n" +
                    "Android ${android.os.Build.VERSION.RELEASE} · ${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}\n"
                shop.corgi.client.core.LogZip.write(logs.files(), about, out)
            }
        }.fold({ tr("Архив сохранён", "Archive saved", "Архів збережено") }, { tr("Не удалось сохранить", "Could not save", "Не вдалося зберегти") })
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Section(tr("Журнал ядра", "Core log", "Журнал ядра")) {
            ChoiceRow(tr("Уровень", "Level", "Рівень"), tr("Применяется при следующем подключении", "Applies on the next connection", "Діє з наступного підключення"),
                Settings.LOG_LEVELS.map { it to if (it == "none") tr("Выключены", "Off", "Вимкнено") else it }, s.logLevel) { save(s.copy(logLevel = it)) }
            ChoiceRow(tr("Хранение журналов", "Keep logs", "Зберігання журналів"), "", Settings.LOG_HOURS.map {
                it.toString() to when (it) { 0 -> tr("Всегда", "Always", "Завжди"); 168 -> tr("7 дней", "7 days", "7 днів"); else -> "$it " + tr("ч", "h", "год") }
            }, s.logHours.toString()) { save(s.copy(logHours = it.toInt())) }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            files.forEach { f -> FilterChip(selected = f == file, onClick = { chosen = f.name }, label = { Text("${f.name} · ${f.length() / 1024} KB") }) }
        }
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), placeholder = { Text(tr("Текст, IP или домен", "Text, IP or domain", "Текст, IP або домен")) }, singleLine = true)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("all" to tr("Все", "All", "Усі"), "error" to "Error", "warning" to "Warning", "info" to "Info").forEach { (key, label) ->
                FilterChip(selected = level == key, onClick = { level = key }, label = { Text(label) }, modifier = Modifier.testTag("level-$key"))
            }
        }
        Text("${lines.size}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        SelectionContainer {
            Column(Modifier.heightIn(max = 420.dp).padding(4.dp)) {
                if (lines.isEmpty()) Text(tr("Записей нет", "No entries", "Записів немає"), color = MaterialTheme.colorScheme.onSurfaceVariant)
                lines.takeLast(200).forEach { line ->
                    Text(line, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                        color = if (Regex("(?i)error|failed|fail").containsMatchIn(line)) Color(0xFFFF5A6E) else MaterialTheme.colorScheme.onSurface)
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedButton(onClick = { revision++ }) { Text(tr("Обновить", "Refresh", "Оновити")) }
            OutlinedButton(onClick = { copy(context, "log", lines.joinToString("\n")) }) { Text(tr("Копировать", "Copy", "Копіювати")) }
            OutlinedButton(onClick = { share(context, files) }) { Text(tr("Экспорт", "Export", "Експорт")) }
            OutlinedButton(onClick = { saveZip.launch(shop.corgi.client.core.LogZip.name(System.currentTimeMillis())) }, modifier = Modifier.testTag("logs-zip")) { Text(".zip") }
            TextButton(onClick = { logs.clear(); revision++ }) { Text(tr("Удалить", "Delete", "Видалити"), color = MaterialTheme.colorScheme.error) }
        }
        if (zipNote.isNotBlank()) Text(zipNote, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
    }
}

/** «Экспорт всех»: the logs as text into any app the user picks (they may contain addresses — the user decides). */
private fun share(context: Context, files: List<File>) {
    val text = files.joinToString("\n\n") { "=== ${it.name} ===\n" + it.readText().takeLast(100_000) }.take(400_000)
    context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), null))
}
