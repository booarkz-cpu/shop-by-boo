package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject

/** One installed app of «Прокси по приложениям» (v1.6.0, N10). */
data class AppEntry(val pkg: String, val label: String, val system: Boolean)

/**
 * The list of «Прокси по приложениям»: search by name or package, system apps hidden unless asked, the chosen ones
 * first; the choice exported and imported as JSON ({"mode": "only"|"except", "apps": [...]}).
 */
object AppList {
    private val PACKAGE = Regex("^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+$")

    fun filter(apps: List<AppEntry>, query: String, system: Boolean, chosen: Set<String>): List<AppEntry> {
        val q = query.trim().lowercase()
        return apps
            .filter { it.system == system }
            .filter { q.isEmpty() || q in it.label.lowercase() || q in it.pkg.lowercase() }
            .sortedWith(compareBy<AppEntry>({ it.pkg !in chosen }, { it.label.lowercase() }))
    }

    fun export(mode: String, apps: Set<String>): String = JSONObject()
        .put("mode", mode)
        .put("apps", JSONArray(apps.sorted()))
        .toString(2)

    /** The mode and the packages of an exported list; a bare JSON array of packages is accepted too. */
    fun import(text: String): Pair<String?, Set<String>> {
        val trimmed = text.trim()
        val (mode, array) =
            if (trimmed.startsWith("[")) {
                null to JSONArray(trimmed)
            } else {
                val json = JSONObject(trimmed)
                json.optString("mode").takeIf { it in listOf("only", "except") } to json.getJSONArray("apps")
            }
        val apps = (0 until array.length()).map { array.getString(it).trim() }.filter { PACKAGE.matches(it) }.toSet()
        require(apps.size <= 2000) { "too many" }
        return mode to apps
    }
}
