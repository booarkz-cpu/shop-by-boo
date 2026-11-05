package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject

/**
 * What the user added: a subscription (URL, updated by itself), single links, or a full Xray JSON config.
 * ``links`` keeps the share links of the last update, so the servers survive without the network.
 */
data class Profile(
    val id: String,
    val name: String,
    val kind: String,                // subscription | links | json
    val url: String = "",
    val links: List<String> = emptyList(),
    val json: String = "",
    val updatedAt: Long = 0,
    val autoUpdateHours: Int = 12,
    val skipped: Int = 0,
    val error: String = "",
) {
    init {
        require(kind in listOf("subscription", "links", "json")) { "kind" }
        require(kind != "subscription" || url.startsWith("https://") || url.startsWith("http://10.0.2.2:")) { "Подписка — только по https://" }
        require(autoUpdateHours in 0..168) { "hours" }
    }

    fun servers(): List<Server> = links.mapNotNull { runCatching { Links.parse(it) }.getOrNull() }

    fun due(now: Long): Boolean = kind == "subscription" && autoUpdateHours > 0 && now - updatedAt >= autoUpdateHours * 3_600_000L

    fun toJson(): JSONObject = JSONObject().put("id", id).put("name", name).put("kind", kind).put("url", url).put("links", JSONArray(links))
        .put("json", json).put("updatedAt", updatedAt).put("autoUpdateHours", autoUpdateHours).put("skipped", skipped).put("error", error)

    companion object {
        fun of(j: JSONObject) = Profile(j.getString("id"), j.getString("name"), j.getString("kind"), j.optString("url"),
            j.optJSONArray("links")?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList(), j.optString("json"),
            j.optLong("updatedAt"), j.optInt("autoUpdateHours", 12), j.optInt("skipped"), j.optString("error"))

        /** What the user pasted or scanned: a subscription URL, links (one per line, or base64), or a JSON config. */
        fun fromText(text: String, id: String, now: Long): Profile {
            val value = text.trim()
            require(value.isNotEmpty()) { "Пусто" }
            if (value.startsWith("{")) {
                ConfigBuilder.fromJson(value, Settings())
                return Profile(id, JSONObject(value).optString("remarks").ifBlank { "Xray JSON" }.take(60), "json", json = value, updatedAt = now)
            }
            if ((value.startsWith("https://") || value.startsWith("http://10.0.2.2:")) && !value.contains("\n")) {
                return Profile(id, value.substringAfter("://").substringBefore("/"), "subscription", url = value)
            }
            val (servers, skipped) = Links.parseBody(value)
            require(servers.isNotEmpty()) { if (skipped > 0) "Эти протоколы не поддерживаются" else "Нет ссылок на серверы" }
            return Profile(id, if (servers.size == 1) servers[0].name else "Ссылки (${servers.size})", "links",
                links = servers.map { it.link }, updatedAt = now, skipped = skipped)
        }
    }
}
