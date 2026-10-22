package shop.remnawave.user.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.view.View
import android.widget.RemoteViews
import org.json.JSONObject
import shop.remnawave.user.MainActivity
import shop.remnawave.user.R
import shop.remnawave.user.SecureTokenStore
import shop.remnawave.user.ShopApi
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.concurrent.thread

/** Home-screen widget. Android calls onUpdate at most every 30 minutes (updatePeriodMillis). */
class CorgiWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, appWidgetIds: IntArray) {
        CorgiWidgetData.renderAll(context)
        val pending = goAsync()
        thread {
            try { CorgiWidgetData.refresh(context) } finally { pending.finish() }
        }
    }
}

/**
 * The widget is readable without the biometric unlock, so it is opt-in and shows only
 * the minimal summary from GET /api/me/widget (no link, balances or contacts). Signing
 * out clears it; a snapshot older than 24 hours is hidden behind "Open the app".
 */
object CorgiWidgetData {
    private const val PREFS = "shop_user"
    private const val KEY_ENABLED = "widget_enabled"
    private const val KEY_SNAPSHOT = "widget_snapshot"
    private const val MAX_AGE_MS = 24 * 60 * 60 * 1000L

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, 0)

    fun enabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, false)

    fun setEnabled(context: Context, on: Boolean) {
        val edit = prefs(context).edit().putBoolean(KEY_ENABLED, on)
        if (!on) edit.remove(KEY_SNAPSHOT)
        edit.apply()
        renderAll(context)
    }

    /** Sign-out: forget the snapshot and the opt-in, so the next account starts hidden. */
    fun clear(context: Context) {
        prefs(context).edit().remove(KEY_SNAPSHOT).putBoolean(KEY_ENABLED, false).apply()
        renderAll(context)
    }

    /** Blocking: fetches a fresh summary when enabled and signed in. Keeps the old snapshot on errors. */
    fun refresh(context: Context) {
        val store = prefs(context)
        if (store.getBoolean(KEY_ENABLED, false)) {
            val base = store.getString("base", "") ?: ""
            val session = SecureTokenStore(store).read()
            if (base.isBlank() || session.isBlank()) {
                store.edit().remove(KEY_SNAPSHOT).apply()
            } else {
                try {
                    val lang = store.getString("lang", "ru") ?: "ru"
                    val data = ShopApi(base, session, lang).get("/api/me/widget") as JSONObject
                    data.put("fetched_at_ms", System.currentTimeMillis())
                    store.edit().putString(KEY_SNAPSHOT, data.toString()).apply()
                } catch (_: Exception) {
                }
            }
        }
        renderAll(context)
    }

    fun renderAll(context: Context) {
        val manager = AppWidgetManager.getInstance(context) ?: return
        val ids = manager.getAppWidgetIds(ComponentName(context, CorgiWidget::class.java))
        if (ids.isEmpty()) return
        manager.updateAppWidget(ids, build(context))
    }

    private fun strings(context: Context, lang: String): JSONObject = try {
        val text = context.assets.open("l10n.json").bufferedReader().use { it.readText() }
        JSONObject(text).optJSONObject(lang) ?: JSONObject(text).getJSONObject("ru")
    } catch (_: Exception) { JSONObject() }

    private fun gigabytes(bytes: Long): String {
        val gb = bytes / 1024.0 / 1024.0 / 1024.0
        return String.format(Locale.ROOT, if (gb >= 10) "%.0f GB" else "%.1f GB", gb)
    }

    private fun build(context: Context): RemoteViews {
        val store = prefs(context)
        val lang = store.getString("lang", "ru") ?: "ru"
        val l10n = strings(context, lang)
        fun t(key: String) = l10n.optString(key, key)
        val views = RemoteViews(context.packageName, R.layout.corgi_widget)
        val open = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        views.setOnClickPendingIntent(R.id.widget_root, PendingIntent.getActivity(context, 7001, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        views.setTextViewText(R.id.widget_title, t("app_name"))
        views.setViewVisibility(R.id.widget_unread, View.GONE)

        val raw = store.getString(KEY_SNAPSHOT, null)
        val snapshot = try { raw?.let { JSONObject(it) } } catch (_: Exception) { null }
        val fresh = snapshot != null && System.currentTimeMillis() - snapshot.optLong("fetched_at_ms") < MAX_AGE_MS
        if (!store.getBoolean(KEY_ENABLED, false) || snapshot == null || !fresh) {
            views.setTextViewText(R.id.widget_state, t("widget_open"))
            views.setTextColor(R.id.widget_state, 0xFF94A3B8.toInt())
            views.setTextViewText(R.id.widget_expiry, if (store.getBoolean(KEY_ENABLED, false)) "" else t("widget_off"))
            views.setTextViewText(R.id.widget_traffic, "")
            views.setTextViewText(R.id.widget_updated, "")
            views.setViewVisibility(R.id.widget_progress, View.GONE)
            return views
        }

        val unread = snapshot.optInt("unread_notifications", 0)
        if (unread > 0) {
            views.setViewVisibility(R.id.widget_unread, View.VISIBLE)
            views.setTextViewText(R.id.widget_unread, "${t("widget_unread")}: $unread")
        }
        val updated = DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(snapshot.optLong("fetched_at_ms")))
        views.setTextViewText(R.id.widget_updated, "${t("widget_updated")} $updated")

        val sub = snapshot.optJSONObject("subscription")
        if (sub == null) {
            views.setTextViewText(R.id.widget_state, t("widget_no_sub"))
            views.setTextColor(R.id.widget_state, 0xFF94A3B8.toInt())
            views.setTextViewText(R.id.widget_expiry, "")
            views.setTextViewText(R.id.widget_traffic, "")
            views.setViewVisibility(R.id.widget_progress, View.GONE)
            return views
        }
        val plan = sub.optString("plan").takeIf { it.isNotBlank() && it != "null" }
        if (plan != null) views.setTextViewText(R.id.widget_title, plan)
        val state = sub.optString("state", "none")
        val (label, color) = when (state) {
            "active" -> t("widget_active") to 0xFF22C55E
            "expiring" -> t("widget_expiring") to 0xFFF59E0B
            "cancel_scheduled" -> t("widget_cancel") to 0xFFF59E0B
            "expired" -> t("widget_expired") to 0xFFEF4444
            else -> t("widget_no_sub") to 0xFF94A3B8
        }
        val days = if (sub.isNull("days_left")) null else sub.optInt("days_left")
        views.setTextViewText(R.id.widget_state, if (days != null && days > 0) "$label · $days ${t("widget_days")}" else label)
        views.setTextColor(R.id.widget_state, color.toInt())
        val expires = sub.optString("expires_at").takeIf { it.isNotBlank() && it != "null" }
        val date = expires?.let {
            try { DateTimeFormatter.ofPattern("dd.MM.yyyy").withZone(ZoneId.systemDefault()).format(Instant.parse(it)) } catch (_: Exception) { null }
        }
        views.setTextViewText(R.id.widget_expiry, if (date != null) "${t("widget_until")} $date" else "")

        val limit = if (sub.isNull("traffic_limit_bytes")) 0L else sub.optLong("traffic_limit_bytes")
        val left = if (sub.isNull("traffic_left_bytes")) null else sub.optLong("traffic_left_bytes")
        when {
            limit <= 0L -> {
                views.setTextViewText(R.id.widget_traffic, t("widget_unlimited"))
                views.setViewVisibility(R.id.widget_progress, View.GONE)
            }
            !sub.optBoolean("traffic_available") || left == null -> {
                views.setTextViewText(R.id.widget_traffic, t("widget_traffic_na"))
                views.setViewVisibility(R.id.widget_progress, View.GONE)
            }
            else -> {
                views.setTextViewText(R.id.widget_traffic, "${t("widget_left")} ${gigabytes(left)} ${t("widget_of")} ${gigabytes(limit)}")
                views.setViewVisibility(R.id.widget_progress, View.VISIBLE)
                views.setProgressBar(R.id.widget_progress, 100, ((left * 100) / limit).toInt().coerceIn(0, 100), false)
            }
        }
        return views
    }
}
