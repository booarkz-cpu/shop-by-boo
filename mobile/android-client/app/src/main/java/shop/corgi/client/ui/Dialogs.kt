package shop.corgi.client.ui

import androidx.compose.runtime.LaunchedEffect
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.IconButton
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.LinearProgressIndicator
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
import shop.corgi.client.core.RoutingProfile
import shop.corgi.client.core.TvReceiver
import shop.corgi.client.core.tr
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.vpn.ClientVpnService
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.concurrent.thread


/** On a TV: a one-time page in the local network; the phone opens it by the QR and sends the subscription. */
@Composable
internal fun ReceiveDialog(store: Store, onDone: () -> Unit) {
    val context = LocalContext.current
    var address by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf("") }
    DisposableEffect(Unit) {
        val receiver = TvReceiver { text ->
            val result = runCatching { store.add(text).also { if (it.kind == "subscription") store.update(it) } }
            android.os.Handler(context.mainLooper).post {
                status = result.fold({ tr("Добавлено: ", "Added: ", "Додано: ") + it.name }, { it.message ?: "error" })
            }
        }
        val ip = TvReceiver.localAddress()
        if (ip == null) status = tr("Нет локальной сети", "No local network", "Немає локальної мережі")
        else address = "http://$ip:${receiver.start()}/${receiver.key}"
        onDispose { receiver.stop() }
    }
    AlertDialog(onDismissRequest = onDone, confirmButton = { TextButton(onClick = onDone) { Text("OK") } },
        title = { Text(tr("Отсканируйте телефоном", "Scan with a phone", "Відскануйте телефоном")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                address?.let { url ->
                    QrImage(url)
                    Text(tr("Телефон должен быть в той же сети. Страница работает 5 минут и принимает одну подписку.",
                        "The phone must be on the same network. The page works for 5 minutes and accepts one subscription.",
                        "Телефон має бути в тій самій мережі. Сторінка працює 5 хвилин і приймає одну підписку."), style = MaterialTheme.typography.bodySmall)
                }
                if (status.isNotBlank()) Text(status)
            }
        })
}

@Composable
internal fun QrImage(text: String) {
    val bitmap = remember(text) {
        val matrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 512, 512)
        Bitmap.createBitmap(512, 512, Bitmap.Config.RGB_565).apply {
            for (x in 0 until 512) for (y in 0 until 512) setPixel(x, y, if (matrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
        }
    }
    Image(bitmap.asImageBitmap(), null, Modifier.size(240.dp))
}

@Composable
internal fun ServerRow(title: String, subtitle: String, selected: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        RadioButton(selected = selected, onClick = onClick)
        Column { Text(title); if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodySmall) }
    }
}

@Composable
internal fun AddDialog(store: Store, initial: String, onDone: () -> Unit) {
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
internal fun QrDialog(text: String, onDone: () -> Unit) {
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
internal fun RoutingScreen(store: Store, refresh: () -> Unit) {
    val context = LocalContext.current
    val s = store.settings
    var rule by remember { mutableStateOf("") }
    var action by remember { mutableStateOf("direct") }
    var message by remember { mutableStateOf("") }
    var profileName by remember { mutableStateOf("") }
    // v1.6.0 (N10): the geo download's progress, null when nothing is being downloaded.
    var geoProgress by remember { mutableStateOf<Float?>(null) }
    var toDelete by remember { mutableStateOf<Rule?>(null) }
    toDelete?.let { r ->
        AlertDialog(onDismissRequest = { toDelete = null }, title = { Text(tr("Удалить правило?", "Delete the rule?", "Видалити правило?")) },
            text = { Text("${r.match} → ${r.action}") },
            confirmButton = { Button(onClick = { store.settings = store.settings.let { it.copy(rules = it.rules - r) }; toDelete = null; refresh() },
                modifier = Modifier.testTag("rule-delete-confirm")) { Text(tr("Удалить", "Delete", "Видалити")) } },
            dismissButton = { TextButton(onClick = { toDelete = null }) { Text(tr("Отмена", "Cancel", "Скасувати")) } })
    }
    Column(Modifier.fillMaxSize()) {
    geoProgress?.let { value ->
        Column(Modifier.fillMaxWidth().padding(12.dp).testTag("geo-progress"), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(tr("Обновление баз данных гео-роутинга…", "Updating the geo-routing databases…", "Оновлення баз гео-маршрутизації…") + " ${(value * 100).toInt()}%",
                style = MaterialTheme.typography.bodyMedium)
            LinearProgressIndicator(progress = { value }, modifier = Modifier.fillMaxWidth())
        }
    }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        // v1.4.0: «Профили маршрутизации» — the mode and rules saved under a name, applied in one tap.
        item { Text(tr("Профили маршрутизации", "Routing profiles", "Профілі маршрутизації"), style = MaterialTheme.typography.titleMedium) }
        items(s.routingProfiles, key = { "profile-" + it.name }) { p ->
            val active = p.routing == s.routing && p.rules == s.rules
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f).clickable { store.settings = s.copy(routing = p.routing, rules = p.rules); refresh() }.testTag("routing-profile")) {
                    Text((if (active) "● " else "") + p.name, style = MaterialTheme.typography.titleSmall)
                    Text(tr("правил: ", "rules: ", "правил: ") + p.rules.size, style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = { store.settings = s.copy(routingProfiles = s.routingProfiles - p); refresh() }) { Text("✕") }
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(value = profileName, onValueChange = { profileName = it.take(40) }, singleLine = true, modifier = Modifier.weight(1f).testTag("profile-name"),
                    placeholder = { Text(tr("Имя профиля", "Profile name", "Назва профілю")) })
                Button(onClick = {
                    val name = profileName.trim()
                    message = runCatching {
                        val profile = RoutingProfile(name, s.routing, s.rules)
                        store.settings = s.copy(routingProfiles = s.routingProfiles.filterNot { it.name == name } + profile)
                        profileName = ""; refresh()
                    }.fold({ tr("Профиль сохранён", "Profile saved", "Профіль збережено") }, { tr("Нужно имя (до 40 символов), не больше 20 профилей", "A name (up to 40 characters), at most 20 profiles", "Потрібна назва (до 40 символів), не більше 20 профілів") })
                }) { Text(tr("Сохранить текущие", "Save current", "Зберегти поточні")) }
            }
        }
        item { Text(tr("Что идёт через VPN", "What goes through the VPN", "Що йде через VPN"), style = MaterialTheme.typography.titleMedium) }
        items(listOf("global" to tr("Всё через VPN", "Everything", "Усе через VPN"),
            "bypass_lan" to tr("Всё, кроме локальной сети", "All but the local network", "Усе, крім локальної мережі"),
            "bypass_ru" to tr("Российские сайты напрямую", "Russian sites direct", "Російські сайти напряму"),
            "custom" to tr("Свои правила", "Own rules", "Власні правила"))) { (key, label) ->
            ServerRow(label, "", s.routing == key) { store.settings = s.copy(routing = key); refresh() }
        }
        item { Text(tr("Правила (домен, IP, geosite:, geoip:)", "Rules (domain, IP, geosite:, geoip:)", "Правила (домен, IP, geosite:, geoip:)"), style = MaterialTheme.typography.titleMedium) }
        // v1.6.0 (N10): a rule goes by a swipe to the left or «⋮ → Удалить», always after a confirmation.
        items(s.rules, key = { "rule-" + it.match + "-" + it.action }) { r -> RuleRow(r) { toDelete = r } }
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
            OutlinedButton(enabled = geoProgress == null, onClick = {
                message = ""
                geoProgress = 0f
                val main = android.os.Handler(context.mainLooper)
                thread {
                    val result = runCatching { store.downloadGeo { value -> main.post { geoProgress = value } } }
                        .fold({ tr("Готово", "Done", "Готово") }, { it.message ?: "error" })
                    main.post { geoProgress = null; message = result; refresh() }
                }
            }) { Text(tr("Скачать geo-файлы", "Download geo files", "Завантажити geo-файли")) }
            if (message.isNotBlank()) Text(message)
        } }
    }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RuleRow(rule: Rule, onDelete: () -> Unit) {
    val swipe = rememberSwipeToDismissBoxState()
    LaunchedEffect(swipe.currentValue) {
        if (swipe.currentValue == SwipeToDismissBoxValue.EndToStart) { onDelete(); swipe.snapTo(SwipeToDismissBoxValue.Settled) }
    }
    var menu by remember { mutableStateOf(false) }
    SwipeToDismissBox(swipe, enableDismissFromStartToEnd = false, modifier = Modifier.testTag("rule"), backgroundContent = {
        Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.errorContainer).padding(horizontal = 16.dp), contentAlignment = Alignment.CenterEnd) {
            Icon(Icons.Filled.Delete, tr("Удалить", "Delete", "Видалити"), tint = MaterialTheme.colorScheme.error)
        }
    }) {
        Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.background).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("${rule.match} → ${rule.action}", Modifier.weight(1f))
            Box {
                IconButton(onClick = { menu = true }, modifier = Modifier.testTag("rule-menu")) { Icon(Icons.Filled.MoreVert, tr("Ещё", "More", "Ще")) }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(text = { Text(tr("Удалить", "Delete", "Видалити"), color = MaterialTheme.colorScheme.error) },
                        leadingIcon = { Icon(Icons.Filled.Delete, null) }, onClick = { menu = false; onDelete() }, modifier = Modifier.testTag("rule-delete"))
                }
            }
        }
    }
}

@Composable
internal fun AppsDialog(context: Context, initial: Set<String>, onDone: (Set<String>?) -> Unit) {
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
