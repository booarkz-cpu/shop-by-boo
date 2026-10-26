package shop.remnawave.user.analytics

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import shop.remnawave.user.BuildConfig
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import kotlin.concurrent.thread

/**
 * Anonymous app statistics («Приложения: аналитика», backend/app/app_growth.py).
 *
 * A random installation id (never the device id), the platform, the app version, the event and
 * the screen. Events wait in memory and leave in batches; nothing is sent when the shop switched
 * the «analytics» layout feature off or when no shop address is known.
 */
object CorgiAnalytics {
    private val queue = mutableListOf<JSONObject>()
    private var lastFlush = 0L
    @Volatile var enabled = true

    fun installId(context: Context): String {
        val prefs = context.getSharedPreferences("shop_user", 0)
        prefs.getString("install_id", null)?.let { return it }
        val id = UUID.randomUUID().toString()
        prefs.edit().putString("install_id", id).putBoolean("install_reported", false).apply()
        return id
    }

    /** First launch after installation: reported once. */
    fun install(context: Context, base: String) {
        val prefs = context.getSharedPreferences("shop_user", 0)
        installId(context)
        if (prefs.getBoolean("install_reported", false)) return
        prefs.edit().putBoolean("install_reported", true).apply()
        track(context, base, "", "install")
    }

    fun track(context: Context, base: String, token: String, event: String, screen: String = "") {
        if (!enabled || base.isBlank()) return
        val row = JSONObject().put("event", event)
        if (screen.isNotBlank()) row.put("screen", screen.lowercase().filter { it.isLetterOrDigit() || it == '_' || it == '-' }.take(32))
        val batch: List<JSONObject>
        synchronized(queue) {
            queue.add(row)
            val now = System.currentTimeMillis()
            // Important steps of the funnel leave at once; screens wait for a batch of ten or half a minute.
            if (event == "screen" && queue.size < 10 && now - lastFlush < 30_000) return
            batch = queue.toList()
            queue.clear()
            lastFlush = now
        }
        val id = installId(context)
        thread {
            try {
                val body = JSONObject().put("install_id", id).put("platform", "android")
                    .put("app_version", BuildConfig.VERSION_NAME.substringBefore("-")).put("events", JSONArray(batch))
                val connection = (URL("$base/api/mobile/events").openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    instanceFollowRedirects = false
                    connectTimeout = 10000
                    readTimeout = 10000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    setRequestProperty("User-Agent", "CorgiLusi-Android-User/3.1.0")
                    setRequestProperty("X-Shop-Client", "android-user")
                    if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
                }
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
                val answer = (if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream)
                    ?.bufferedReader()?.use { it.readText() }.orEmpty()
                if (answer.contains("\"enabled\":false") || answer.contains("\"enabled\": false")) enabled = false
            } catch (_: Exception) {
                // Statistics never get in the way: a lost batch is not retried.
            }
        }
    }
}
