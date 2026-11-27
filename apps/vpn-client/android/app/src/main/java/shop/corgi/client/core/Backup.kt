package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

/**
 * «Резервное копирование»: providers, servers, routing rules and every setting in one JSON file, a QR code or a link
 * (`corgi://restore/…`, gzip + base64url). The local proxy's login and password are not in it — the new device makes
 * its own. Restoring shows what comes back before anything is replaced.
 */
data class Backup(val profiles: List<Profile>, val settings: Settings, val activeProfile: String, val activeServer: String, val created: Long) {
    fun toJson(): JSONObject = JSONObject().put("format", FORMAT).put("version", VERSION).put("created", created)
        .put("profiles", JSONArray(profiles.map { it.toJson() }))
        .put("settings", settings.toJson().apply { remove("proxyUser"); remove("proxyPass") })
        .put("activeProfile", activeProfile).put("activeServer", activeServer)

    /** What the preview shows: the providers and how many servers each has. */
    fun summary(): List<String> = profiles.map { p -> "${p.title} — ${if (p.kind == "json") 1 else p.servers().size}" }

    fun link(): String = "corgi://restore/" + encode(toJson().toString())

    companion object {
        const val FORMAT = "corgi-client-backup"
        private const val VERSION = 1

        fun of(json: JSONObject): Backup {
            require(json.optString("format") == FORMAT) { tr("Это не резервная копия «Корги Люси: клиента»", "Not a «Corgi Lusi: client» backup", "Це не резервна копія «Коргі Люсі: клієнта»") }
            val version = json.opt("version")
            require(version == VERSION || version == VERSION.toLong()) {
                tr("Неподдерживаемая версия резервной копии", "Unsupported backup version", "Непідтримувана версія резервної копії")
            }
            val items = requireNotNull(json.optJSONArray("profiles")) {
                tr("Повреждён список профилей в резервной копии", "Invalid profile list in backup", "Пошкоджено список профілів у резервній копії")
            }
            val settings = requireNotNull(json.optJSONObject("settings")) {
                tr("Повреждены настройки в резервной копии", "Invalid settings in backup", "Пошкоджено налаштування в резервній копії")
            }
            val profiles = (0 until items.length()).map { Profile.of(items.getJSONObject(it)) }
            return Backup(profiles, Settings.of(settings), json.optString("activeProfile"), json.optString("activeServer", "auto"), json.optLong("created"))
        }

        /** A backup from a file's text or a corgi://restore/ link. */
        fun parse(text: String): Backup {
            val value = text.trim()
            return of(JSONObject(if (value.startsWith("corgi://restore/")) decode(value.removePrefix("corgi://restore/")) else value))
        }

        fun encode(text: String): String {
            val out = ByteArrayOutputStream()
            GZIPOutputStream(out).use { it.write(text.toByteArray(Charsets.UTF_8)) }
            return java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(out.toByteArray())
        }

        fun decode(value: String): String = GZIPInputStream(ByteArrayInputStream(java.util.Base64.getUrlDecoder().decode(value)))
            .use { String(it.readBytes(), Charsets.UTF_8) }
    }
}

/**
 * URL schemes for Tasker, Shortcuts and links: corgi://connect | open | disconnect | close | toggle | import/{base64} |
 * add/{url} | routing/add/{base64} | routing/onadd/{base64} | restore/{backup}. Imports and rules are confirmed in the app.
 */
sealed class Scheme {
    data object Connect : Scheme()
    data object Open : Scheme()
    data object Disconnect : Scheme()
    data object Close : Scheme()
    data object Toggle : Scheme()
    data class Import(val text: String) : Scheme()
    data class Rules(val rules: List<Rule>, val apply: Boolean) : Scheme()
    data class Restore(val link: String) : Scheme()

    companion object {
        fun parse(uri: String): Scheme? {
            if (!uri.startsWith("corgi://")) return null
            val rest = uri.removePrefix("corgi://")
            val head = rest.substringBefore("/").lowercase()
            val tail = rest.substringAfter("/", "")
            return when (head) {
                "connect" -> Connect; "open" -> Open; "disconnect" -> Disconnect; "close" -> Close; "toggle" -> Toggle
                "import" -> Import(b64(tail))
                "add" -> Import(java.net.URLDecoder.decode(tail, "UTF-8"))
                "restore" -> Restore(uri)
                "routing" -> {
                    val action = tail.substringBefore("/").lowercase()
                    if (action !in listOf("add", "onadd")) return null
                    Rules(rules(b64(tail.substringAfter("/"))), action == "onadd")
                }
                else -> null
            }
        }

        private fun b64(value: String): String = String(java.util.Base64.getMimeDecoder().decode(value.replace('-', '+').replace('_', '/')), Charsets.UTF_8)

        /** A JSON array of {"match","action"}, or lines «example.com direct» / «geosite:ads block». */
        fun rules(text: String): List<Rule> {
            val t = text.trim()
            if (t.startsWith("[")) return JSONArray(t).let { a -> (0 until a.length()).map { a.getJSONObject(it) }.map { Rule(Rule.normalize(it.getString("match")), it.optString("action", "proxy")) } }
            return t.lines().map { it.trim() }.filter { it.isNotBlank() }.map { line ->
                val parts = line.split(Regex("[\\s,]+"))
                Rule(Rule.normalize(parts[0]), parts.getOrNull(1)?.lowercase() ?: "proxy")
            }.take(200)
        }
    }
}
