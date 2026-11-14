package shop.corgi.client.ui

import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.core.graphics.drawable.toBitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import shop.corgi.client.core.AppEntry
import shop.corgi.client.core.AppList
import shop.corgi.client.core.Settings
import shop.corgi.client.core.tr

/** v1.6.0 (N10): every installed app with its icon (this app is never in the list). */
private fun installed(context: Context): List<AppEntry> {
    val pm = context.packageManager
    return pm.getInstalledApplications(PackageManager.GET_META_DATA)
        .filter { it.packageName != context.packageName }
        .map {
            AppEntry(
                it.packageName,
                pm.getApplicationLabel(it).toString(),
                (it.flags and ApplicationInfo.FLAG_SYSTEM) != 0 && (it.flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) == 0
            )
        }
}

/**
 * «Прокси по приложениям» in the manner of Incy and NekoBox: two mode cards, search, user and system apps on tabs
 * (system ones hidden until their tab is opened), the number chosen, and import / export of the list as JSON.
 */
@Composable
internal fun AppsScreen(s: Settings, save: (Settings) -> Unit, share: (String) -> Unit, paste: () -> String?) {
    val context = LocalContext.current
    val apps by produceState<List<AppEntry>?>(null) { value = withContext(Dispatchers.IO) { installed(context) } }
    var query by remember { mutableStateOf("") }
    var system by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                Triple(
                    "only",
                    tr("Только через туннель", "Only through the tunnel", "Лише через тунель"),
                    tr("Выбранные — через VPN, остальные напрямую", "The chosen go through the VPN", "Вибрані — через VPN")
                ),
                Triple(
                    "except",
                    tr("Обход", "Bypass", "Обхід"),
                    tr("Выбранные — напрямую, остальные через VPN", "The chosen bypass the VPN", "Вибрані — напряму")
                )
            ).forEach { (mode, title, hint) ->
                val on = s.appsMode == mode
                Card(
                    Modifier.weight(1f).clickable { save(s.copy(appsMode = if (on) "all" else mode)) }.testTag("apps-mode-$mode"),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = if (on) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Text((if (on) "● " else "") + title, style = MaterialTheme.typography.titleSmall)
                        Text(hint, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        if (s.appsMode == "all") {
            Text(
                tr(
                    "Сейчас все приложения идут через VPN — выберите режим выше.",
                    "All apps go through the VPN now — pick a mode above.",
                    "Зараз усі застосунки йдуть через VPN — оберіть режим."
                )
            )
        }
        OutlinedTextField(
            query,
            { query = it.take(60) },
            Modifier.fillMaxWidth().testTag("apps-search"),
            singleLine = true,
            leadingIcon = {
                Icon(Icons.Filled.Search, null)
            },
            placeholder = { Text(tr("Поиск приложения", "Search an app", "Пошук застосунку")) }
        )
        TabRow(if (system) 1 else 0) {
            Tab(!system, { system = false }, text = { Text(tr("Пользовательские", "User", "Користувацькі")) })
            Tab(system, { system = true }, Modifier.testTag("apps-system-tab"), text = { Text(tr("Системные", "System", "Системні")) })
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(tr("Выбрано: ", "Chosen: ", "Вибрано: ") + s.apps.size, Modifier.weight(1f).testTag("apps-count"))
            OutlinedButton({
                share(AppList.export(s.appsMode.takeIf { it != "all" } ?: "only", s.apps))
            }) { Text(tr("Экспорт", "Export", "Експорт")) }
            OutlinedButton({
                message = runCatching {
                    val (mode, chosen) = AppList.import(paste() ?: "")
                    save(s.copy(apps = chosen, appsMode = mode ?: s.appsMode))
                    tr("Импортировано: ", "Imported: ", "Імпортовано: ") + chosen.size
                }.getOrElse {
                    tr(
                        "В буфере нет списка приложений (JSON)",
                        "No list of apps (JSON) in the clipboard",
                        "У буфері немає списку застосунків (JSON)"
                    )
                }
            }) { Text(tr("Импорт", "Import", "Імпорт")) }
        }
        if (message.isNotBlank()) Text(message, style = MaterialTheme.typography.bodySmall)
        val list = apps
        if (list == null) {
            Text(tr("Загрузка списка приложений…", "Loading the apps…", "Завантаження застосунків…"))
        } else {
            LazyColumn(Modifier.fillMaxWidth().weight(1f).testTag("apps-list")) {
                items(AppList.filter(list, query, system, s.apps), key = { it.pkg }) { app ->
                    val chosen = app.pkg in s.apps
                    Row(
                        Modifier.fillMaxWidth().clickable {
                            save(s.copy(apps = if (chosen) s.apps - app.pkg else s.apps + app.pkg))
                        }.padding(vertical = 6.dp).testTag("app-row"),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        AppIcon(app.pkg)
                        Column(Modifier.weight(1f)) {
                            Text(app.label, style = MaterialTheme.typography.bodyLarge)
                            Text(app.pkg, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Checkbox(chosen, { on -> save(s.copy(apps = if (on) s.apps + app.pkg else s.apps - app.pkg)) })
                    }
                }
            }
        }
    }
}

@Composable
private fun AppIcon(pkg: String) {
    val context = LocalContext.current
    var icon by remember(pkg) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(pkg) {
        icon =
            withContext(Dispatchers.IO) {
                runCatching { context.packageManager.getApplicationIcon(pkg).toBitmap(96, 96).asImageBitmap() }.getOrNull()
            }
    }
    Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) { icon?.let { Image(it, null, Modifier.size(40.dp)) } }
}
