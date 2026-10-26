package shop.remnawave.user.ui

import android.content.Context
import androidx.compose.ui.graphics.Color
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** One button of a section, as the shop administrator configured it (GET /api/mobile/layout). */
data class LayoutButton(
    val id: String,
    val label: String,
    val action: String,
    val target: String,
    val style: String,
    val icon: String,
    val audience: String,
)

data class LayoutBanner(val url: String, val link: String)

data class LayoutSection(
    val id: String,
    val kind: String,
    val tab: Boolean,
    val title: String,
    val subtitle: String,
    val body: String,
    val icon: String,
    val banner: LayoutBanner?,
    val buttons: List<LayoutButton>,
)

data class LayoutTheme(
    val accent: Color,
    val accent2: Color,
    val background: Color,
    val surface: Color,
    val surface2: Color,
    val text: Color,
    val muted: Color,
    val success: Color,
    val danger: Color,
    val radius: Int,
)

data class AppLayout(
    val lang: String,
    val version: String,
    val theme: LayoutTheme,
    val texts: Map<String, String>,
    val tabs: List<String>,
    val sections: List<LayoutSection>,
    val links: Map<String, String>,
    /** Replacements of the app strings (l10n.json keys) set in the admin panel. */
    val strings: Map<String, String> = emptyMap(),
    /** Screen blocks switched on or off in the admin panel; missing means on. */
    val features: Map<String, Boolean> = emptyMap(),
) {
    fun section(id: String): LayoutSection? = sections.firstOrNull { it.id == id }
    fun text(key: String): String = texts[key] ?: key
    fun feature(key: String): Boolean = features[key] ?: true
}

/** Actions the app implements; a button with anything else is not drawn. */
val KNOWN_ACTIONS = setOf(
    "connect", "open", "url", "document", "cabinet", "telegram_channel", "import_app", "copy_subscription", "show_qr", "copy_id",
    "buy", "pay_wallet", "trial", "topup", "redeem", "auto_location", "share_referral", "copy_referral", "family_invite",
    "support_ticket", "report_problem", "language", "push_toggle", "widget_toggle", "passkey_add", "refresh", "sign_out",
)

private fun color(raw: String?, fallback: Long): Color {
    val value = raw.orEmpty()
    if (!Regex("^#[0-9a-fA-F]{6}$").matches(value)) return Color(fallback)
    return Color(0xFF000000 or value.substring(1).toLong(16))
}

private fun JSONObject.str(key: String): String = if (isNull(key)) "" else optString(key, "")

fun parseLayout(doc: JSONObject): AppLayout {
    val t = doc.optJSONObject("theme") ?: JSONObject()
    val theme = LayoutTheme(
        accent = color(t.optString("accent"), 0xFFFF8A1F),
        accent2 = color(t.optString("accent_2"), 0xFFFFC069),
        background = color(t.optString("background"), 0xFF0E0F14),
        surface = color(t.optString("surface"), 0xFF1A1C24),
        surface2 = color(t.optString("surface_2"), 0xFF252833),
        text = color(t.optString("text"), 0xFFF5F2EE),
        muted = color(t.optString("muted"), 0xFF9A97A3),
        success = color(t.optString("success"), 0xFF3DDC84),
        danger = color(t.optString("danger"), 0xFFFF5A6E),
        radius = t.optInt("radius", 22).coerceIn(0, 40),
    )
    val texts = mutableMapOf<String, String>()
    doc.optJSONObject("texts")?.let { obj -> obj.keys().forEach { texts[it] = obj.optString(it) } }
    val links = mutableMapOf<String, String>()
    doc.optJSONObject("links")?.let { obj -> obj.keys().forEach { links[it] = obj.optString(it) } }
    val strings = mutableMapOf<String, String>()
    doc.optJSONObject("strings")?.let { obj -> obj.keys().forEach { k -> obj.optString(k).takeIf { it.isNotBlank() }?.let { strings[k] = it } } }
    val features = mutableMapOf<String, Boolean>()
    doc.optJSONObject("features")?.let { obj -> obj.keys().forEach { features[it] = obj.optBoolean(it, true) } }
    val sections = mutableListOf<LayoutSection>()
    val rows = doc.optJSONArray("sections") ?: JSONArray()
    for (i in 0 until rows.length()) {
        val s = rows.optJSONObject(i) ?: continue
        val buttons = mutableListOf<LayoutButton>()
        val b = s.optJSONArray("buttons") ?: JSONArray()
        for (j in 0 until b.length()) {
            val row = b.optJSONObject(j) ?: continue
            val action = row.str("action")
            if (action !in KNOWN_ACTIONS) continue
            buttons += LayoutButton(row.str("id"), row.str("label"), action, row.str("target"), row.optString("style", "secondary"),
                row.str("icon"), row.optString("audience", "any"))
        }
        val banner = s.optJSONObject("banner")?.let { LayoutBanner(it.str("url"), it.str("link")) }?.takeIf { it.url.isNotBlank() }
        sections += LayoutSection(s.str("id"), s.str("kind"), s.optBoolean("tab"), s.str("title"), s.str("subtitle"), s.str("body"),
            s.str("icon"), banner, buttons)
    }
    val tabs = mutableListOf<String>()
    val tabRows = doc.optJSONArray("tabs") ?: JSONArray()
    for (i in 0 until tabRows.length()) tabRows.optString(i).takeIf { id -> sections.any { it.id == id } }?.let { tabs += it }
    return AppLayout(doc.optString("lang", "ru"), doc.optString("version"), theme, texts, tabs, sections, links, strings, features)
}

/**
 * Layout source: the shop (with ETag revalidation), then the copy saved after the last success,
 * then the default bundled with the app. The app never shows an empty screen because of the layout.
 */
object LayoutStore {
    private const val PREFS = "shop_layout"

    fun bundled(context: Context, lang: String): AppLayout {
        val text = context.assets.open("default_layout.json").bufferedReader().use { it.readText() }
        val all = JSONObject(text)
        return parseLayout(all.optJSONObject(lang) ?: all.getJSONObject("ru"))
    }

    fun cached(context: Context, base: String, lang: String): AppLayout? {
        val raw = context.getSharedPreferences(PREFS, 0).getString("doc:$base:$lang", null) ?: return null
        return try { parseLayout(JSONObject(raw)) } catch (_: Exception) { null }
    }

    /** Blocking: call from a worker thread. Returns null when nothing changed or the shop is unreachable. */
    fun fetch(context: Context, base: String, lang: String): AppLayout? {
        val prefs = context.getSharedPreferences(PREFS, 0)
        val etag = prefs.getString("etag:$base:$lang", null)
        return try {
            val connection = (URL("$base/api/mobile/layout?lang=$lang").openConnection() as HttpURLConnection).apply {
                instanceFollowRedirects = false
                connectTimeout = 10000
                readTimeout = 10000
                setRequestProperty("Accept", "application/json")
                setRequestProperty("X-Shop-Client", "android-user")
                if (etag != null && prefs.contains("doc:$base:$lang")) setRequestProperty("If-None-Match", etag)
            }
            when (connection.responseCode) {
                304 -> null
                in 200..299 -> {
                    val text = connection.inputStream.bufferedReader().use { it.readText() }
                    if (text.length > 512 * 1024) return null
                    val layout = parseLayout(JSONObject(text))
                    prefs.edit().putString("doc:$base:$lang", text).putString("etag:$base:$lang", connection.getHeaderField("ETag") ?: "").apply()
                    layout
                }
                else -> null
            }
        } catch (_: Exception) {
            null
        }
    }
}
