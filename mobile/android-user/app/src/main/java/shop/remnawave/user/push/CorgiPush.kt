package shop.remnawave.user.push

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.tasks.Tasks
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import org.json.JSONObject
import shop.remnawave.user.BuildConfig
import shop.remnawave.user.MainActivity
import shop.remnawave.user.R
import shop.remnawave.user.SecureTokenStore
import shop.remnawave.user.ShopApi
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Opt-in FCM push. The shop server keeps the provider credentials; the app only holds
 * public Firebase client identifiers from BuildConfig. A token is registered for the
 * current signed-in session and unregistered on sign-out, so a shared phone never
 * receives notifications of a previous account.
 */
object CorgiPush {
    const val CHANNEL = "corgi_default"
    const val EXTRA_TAB = "open_tab"
    private const val PREFS = "shop_user"
    private const val KEY_ENABLED = "push_enabled"
    private const val KEY_TOKEN = "push_token"

    fun buildSupportsPush(): Boolean = listOf(
        BuildConfig.FIREBASE_APP_ID, BuildConfig.FIREBASE_API_KEY, BuildConfig.FIREBASE_PROJECT_ID, BuildConfig.FIREBASE_SENDER_ID,
    ).all { it.isNotBlank() }

    fun enabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, false)

    fun permissionGranted(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, 0)

    private fun firebase(context: Context): Boolean {
        if (!buildSupportsPush()) return false
        if (FirebaseApp.getApps(context).isEmpty()) {
            val options = FirebaseOptions.Builder()
                .setApplicationId(BuildConfig.FIREBASE_APP_ID)
                .setApiKey(BuildConfig.FIREBASE_API_KEY)
                .setProjectId(BuildConfig.FIREBASE_PROJECT_ID)
                .setGcmSenderId(BuildConfig.FIREBASE_SENDER_ID)
                .build()
            FirebaseApp.initializeApp(context.applicationContext, options)
        }
        return true
    }

    /** Groups of notifications in the Android settings («Приложения: стиль push-уведомлений» → группа). */
    private val CHANNELS = mapOf(
        "important" to Pair("Подписка и оплата", NotificationManager.IMPORTANCE_HIGH),
        "service" to Pair("Сервис и поддержка", NotificationManager.IMPORTANCE_DEFAULT),
        "promo" to Pair("Акции и розыгрыши", NotificationManager.IMPORTANCE_DEFAULT),
    )

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) == null)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.app_name), NotificationManager.IMPORTANCE_DEFAULT))
        CHANNELS.forEach { (id, value) ->
            if (manager.getNotificationChannel("corgi_$id") == null)
                manager.createNotificationChannel(NotificationChannel("corgi_$id", value.first, value.second))
        }
    }

    /** Blocking: registers the FCM token for the current session. Call off the main thread. */
    fun register(context: Context, base: String, session: String, lang: String, knownToken: String? = null): JSONObject {
        check(firebase(context)) { "push_unavailable" }
        ensureChannel(context)
        val token = knownToken ?: Tasks.await(FirebaseMessaging.getInstance().token, 20, TimeUnit.SECONDS)
        val store = prefs(context)
        val previous = store.getString(KEY_TOKEN, null)
        val body = JSONObject()
            .put("platform", "android")
            .put("token", token)
            .put("app_version", BuildConfig.VERSION_NAME.take(32))
            .put("locale", lang.take(8))
        if (!previous.isNullOrBlank() && previous != token) body.put("replaces", previous)
        val response = ShopApi(base, session, lang).post("/api/me/push/devices", body) as JSONObject
        store.edit().putString(KEY_TOKEN, token).putBoolean(KEY_ENABLED, true).apply()
        return response
    }

    /** Blocking: revokes the token on the server and deletes it locally. Never throws. */
    fun unregister(context: Context, base: String, session: String, lang: String) {
        val store = prefs(context)
        val token = store.getString(KEY_TOKEN, null)
        store.edit().remove(KEY_TOKEN).putBoolean(KEY_ENABLED, false).apply()
        if (!token.isNullOrBlank() && base.isNotBlank() && session.isNotBlank()) {
            try { ShopApi(base, session, lang).post("/api/me/push/devices/unregister", JSONObject().put("token", token)) } catch (_: Exception) { }
        }
        if (!token.isNullOrBlank() && firebase(context)) {
            try { Tasks.await(FirebaseMessaging.getInstance().deleteToken(), 20, TimeUnit.SECONDS) } catch (_: Exception) { }
        }
    }

    private fun openIntent(context: Context, section: String, requestCode: Int): PendingIntent {
        val open = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra(EXTRA_TAB, section.ifBlank { "notifications" })
        return PendingIntent.getActivity(context, requestCode, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    /** A picture of the push: https only, at most 1 MB, a few seconds; without it the push still shows. */
    private fun picture(url: String): android.graphics.Bitmap? {
        if (!url.startsWith("https://")) return null
        return try {
            val connection = (java.net.URL(url).openConnection() as java.net.HttpURLConnection).apply {
                instanceFollowRedirects = false; connectTimeout = 5000; readTimeout = 5000
            }
            if (connection.responseCode !in 200..299) return null
            val bytes = connection.inputStream.use { it.readBytes() }
            if (bytes.size > 1_000_000) null else android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        } catch (_: Exception) { null }
    }

    /** Styled push from the shop: data fields of push.py send_fcm (title, body, image, buttons, channel, accent…). */
    fun show(context: Context, data: Map<String, String>) {
        if (!permissionGranted(context)) return
        ensureChannel(context)
        val id = data["notification_id"]?.toIntOrNull() ?: (System.currentTimeMillis() and 0x7fffffff).toInt()
        val body = data["body"].orEmpty()
        val channel = data["channel"]?.takeIf { it in CHANNELS }?.let { "corgi_$it" } ?: CHANNEL
        val builder = NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.corgi_logo)
            .setContentTitle(data["title"] ?: context.getString(R.string.app_name))
            .setContentText(body)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setAutoCancel(true)
            .setContentIntent(openIntent(context, data["section"].orEmpty(), id))
        try { data["accent"]?.takeIf { it.matches(Regex("#[0-9a-fA-F]{6}")) }?.let { builder.setColor(android.graphics.Color.parseColor(it)).setColorized(false) } } catch (_: Exception) { }
        if (data["sound"] == "0") builder.setSilent(true)
        if (data["large_icon"] != "0") android.graphics.BitmapFactory.decodeResource(context.resources, R.drawable.corgi_logo)?.let { builder.setLargeIcon(it) }
        data["group"]?.takeIf { it.isNotBlank() }?.let { builder.setGroup("corgi_$it") }
        val image = picture(data["image"].orEmpty())
        if (image != null) builder.setStyle(NotificationCompat.BigPictureStyle().bigPicture(image).setSummaryText(body))
        else builder.setStyle(NotificationCompat.BigTextStyle().bigText(body))
        try {
            val buttons = org.json.JSONArray(data["buttons"] ?: "[]")
            for (i in 0 until minOf(2, buttons.length())) {
                val button = buttons.optJSONObject(i) ?: continue
                val label = button.optString("label").take(24)
                if (label.isNotBlank()) builder.addAction(0, label, openIntent(context, button.optString("section"), id * 4 + i + 1))
            }
        } catch (_: Exception) { }
        try { NotificationManagerCompat.from(context).notify(id, builder.build()) } catch (_: SecurityException) { }
    }

    fun show(context: Context, title: String?, body: String?, notificationId: String?) =
        show(context, mapOf("title" to (title ?: ""), "body" to body.orEmpty(), "notification_id" to (notificationId ?: "")).filterValues { it.isNotEmpty() })
}

class CorgiMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        val prefs = getSharedPreferences("shop_user", 0)
        if (!prefs.getBoolean("push_enabled", false)) return
        val base = prefs.getString("base", "") ?: ""
        val session = SecureTokenStore(prefs).read()
        if (base.isBlank() || session.isBlank()) return
        val lang = prefs.getString("lang", "ru") ?: "ru"
        thread { try { CorgiPush.register(applicationContext, base, session, lang, token) } catch (_: Exception) { } }
    }

    // Styled pushes are data messages drawn here, in the foreground and the background alike.
    // An older shop sends a notification message: the system shows it in the background.
    override fun onMessageReceived(message: RemoteMessage) {
        val notification = message.notification
        if (notification != null) {
            CorgiPush.show(this, notification.title, notification.body, message.data["notification_id"])
            return
        }
        if (message.data["title"].isNullOrBlank() && message.data["body"].isNullOrBlank()) return
        CorgiPush.show(this, message.data)
    }
}
