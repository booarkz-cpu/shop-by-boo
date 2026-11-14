package shop.remnawave.admin.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.Modifier
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * v3.6.0 (the window), v3.7.0 (the background update, AppUpdater): the app finds its own new version in the shop's latest release on GitHub. Every release carries
 * corgi-lusi-android-admin.json next to corgi-lusi-android-admin.apk:
 * {"versionCode": 3600, "versionName": "3.6.0", "sha256": "…", "apk": "https://github.com/…/corgi-lusi-android-admin.apk"}.
 * The app compares versionCode once a day and offers the APK; Android checks that the signature matches the
 * installed app. An app installed by a store is updated by the store and never asks GitHub.
 */
data class AppUpdate(val versionCode: Int, val versionName: String, val sha256: String, val apk: String) {
    companion object {
        const val RELEASES = "https://github.com/booarkz-cpu/shop-by-boo/releases/"
        const val MANIFEST = RELEASES + "latest/download/corgi-lusi-android-admin.json"
        const val DAY = 86_400_000L
        /** v28.137.0: GitHub is asked at most every 3 hours (was once a day); the background job runs every 6 hours. */
        const val CHECK = 3 * 3_600_000L
        const val JOB = 6 * 3_600_000L
        private val SHA = Regex("^[0-9a-f]{64}$")
        private val NAME = Regex("^\\d+\\.\\d+\\.\\d+$")
        private val STORES = setOf("com.android.vending", "com.huawei.appmarket", "ru.vk.store", "com.xiaomi.mipicks", "com.sec.android.app.samsungapps")

        fun parse(text: String): AppUpdate {
            val j = JSONObject(text)
            val u = AppUpdate(j.getInt("versionCode"), j.getString("versionName"), j.getString("sha256").lowercase(), j.getString("apk"))
            require(u.versionCode > 0 && SHA.matches(u.sha256) && NAME.matches(u.versionName)) { "manifest" }
            require(u.apk.startsWith(RELEASES) && u.apk.endsWith("/corgi-lusi-android-admin.apk")) { "apk url" }
            return u
        }

        /** The newer one, or null when the app is up to date. */
        fun newer(text: String, current: Int): AppUpdate? = parse(text).takeIf { it.versionCode > current }

        /** A store updates its own installs: the app must not offer an APK from outside. */
        fun fromStore(installer: String?): Boolean = installer in STORES

        /** Whether to ask GitHub now: at most once a day. */
        fun due(now: Long, checkedAt: Long): Boolean = now - checkedAt >= CHECK || checkedAt > now

        /** What to show: nothing for a version the person already put off. */
        fun offer(found: AppUpdate?, dismissedCode: Int): AppUpdate? = found?.takeIf { it.versionCode > dismissedCode }

        fun installer(context: Context): String? = runCatching {
            if (Build.VERSION.SDK_INT >= 30) context.packageManager.getInstallSourceInfo(context.packageName).installingPackageName
            else @Suppress("DEPRECATION") context.packageManager.getInstallerPackageName(context.packageName)
        }.getOrNull()

        /** The newer version in the latest release, asked right now (the daily job; call off the main thread). */
        fun latest(current: Int): AppUpdate? = newer(fetch(), current)

        private fun fetch(): String {
            val connection = (URL(MANIFEST).openConnection() as HttpURLConnection).apply {
                connectTimeout = 8000; readTimeout = 8000; instanceFollowRedirects = true
            }
            try {
                require(connection.responseCode == 200) { "http" }
                return connection.inputStream.use { String(it.readNBytesCompat(8192)) }
            } finally {
                connection.disconnect()
            }
        }

        private fun java.io.InputStream.readNBytesCompat(limit: Int): ByteArray {
            val buffer = ByteArray(limit); var size = 0
            while (size < limit) { val n = read(buffer, size, limit - size); if (n < 0) break; size += n }
            return buffer.copyOf(size)
        }

        /** Call off the main thread. Null: up to date, put off, installed by a store, checked today or no network. */
        fun check(context: Context, current: Int, debug: Boolean, now: Long = System.currentTimeMillis()): AppUpdate? {
            if (debug || fromStore(installer(context))) return null
            val prefs = context.getSharedPreferences("app_update", 0)
            if (!due(now, prefs.getLong("checked", 0))) return null
            val found = runCatching { newer(fetch(), current) }.getOrElse { return null }
            prefs.edit().putLong("checked", now).apply()
            return offer(found, prefs.getInt("dismissed", 0))
        }

        fun dismiss(context: Context, update: AppUpdate) {
            context.getSharedPreferences("app_update", 0).edit().putInt("dismissed", update.versionCode).apply()
        }
    }
}

/** «Доступна версия …»: «Обновить» opens the APK of the release in the browser, «Позже» puts this version off. */
@Composable
fun AppUpdateDialog(current: Int, debug: Boolean, skip: Boolean, t: (String) -> String) {
    val context = LocalContext.current
    var update by remember { mutableStateOf<AppUpdate?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        if (skip) return@LaunchedEffect
        if (!debug) AppUpdater.schedule(context)   // v3.7.0: the daily background update
        val found = withContext(Dispatchers.IO) { AppUpdate.check(context, current, debug) } ?: return@LaunchedEffect
        // v28.137.0 (owner: «без участия пользователя от слова совсем»): downloaded and installed at once; the system asks
        // only where it must (Android 11 and older). The window is left for a failed download.
        val installed = withContext(Dispatchers.IO) {
            runCatching { AppUpdater.install(context, AppUpdater.download(context, found), background = false, resumeVpn = AppUpdater.vpnRunning(context)) }.isSuccess
        }
        if (!installed) update = found
    }
    val found = update ?: return
    AlertDialog(
        modifier = Modifier.testTag("app-update"),
        onDismissRequest = { update = null },
        title = { Text(t("update_title").replace("{version}", found.versionName)) },
        text = { Text(t("update_body")) },
        confirmButton = {
            TextButton(onClick = {
                update = null
                // v3.7.0: downloaded and checked by the app, installed by the system; the browser is the fallback.
                scope.launch(Dispatchers.IO) {
                    runCatching { AppUpdater.install(context, AppUpdater.download(context, found), background = false) }.onFailure {
                        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(found.apk)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                    }
                }
            }) { Text(t("update_install")) }
        },
        dismissButton = { TextButton(onClick = { AppUpdate.dismiss(context, found); update = null }) { Text(t("update_later")) } }
    )
}
