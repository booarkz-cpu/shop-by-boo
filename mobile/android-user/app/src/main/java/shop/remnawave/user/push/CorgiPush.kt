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

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) != null) return
        manager.createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.app_name), NotificationManager.IMPORTANCE_DEFAULT))
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

    fun show(context: Context, title: String?, body: String?, notificationId: String?) {
        if (!permissionGranted(context)) return
        ensureChannel(context)
        val open = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra(EXTRA_TAB, "notifications")
        val id = notificationId?.toIntOrNull() ?: (System.currentTimeMillis() and 0x7fffffff).toInt()
        val pending = PendingIntent.getActivity(context, id, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.corgi_logo)
            .setContentTitle(title ?: context.getString(R.string.app_name))
            .setContentText(body.orEmpty())
            .setStyle(NotificationCompat.BigTextStyle().bigText(body.orEmpty()))
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        try { NotificationManagerCompat.from(context).notify(id, notification) } catch (_: SecurityException) { }
    }
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

    // Background notification messages are shown by the system; this handles the foreground case.
    override fun onMessageReceived(message: RemoteMessage) {
        val notification = message.notification ?: return
        CorgiPush.show(this, notification.title, notification.body, message.data["notification_id"])
    }
}
