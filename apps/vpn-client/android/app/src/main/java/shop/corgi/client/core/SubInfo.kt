package shop.corgi.client.core

import org.json.JSONObject

/**
 * What a subscription says about itself in its response headers (Remnawave, Marzban, 3x-ui and others):
 * «subscription-userinfo» (traffic and expiry), «profile-title», «support-url», «profile-web-page-url»,
 * «profile-update-interval» (hours) and «announce». Shown on the provider card; nothing is invented when a header is missing.
 */
data class SubInfo(
    val title: String = "",
    val upload: Long = 0,
    val download: Long = 0,
    val total: Long = 0,          // 0 — unlimited
    val expire: Long = 0,         // unix seconds; 0 — no end
    val supportUrl: String = "",
    val webUrl: String = "",
    val updateHours: Int = 0,
    val announce: String = "",
) {
    val used: Long get() = upload + download
    val empty: Boolean get() = this == SubInfo()

    fun toJson(): JSONObject = JSONObject().put("title", title).put("upload", upload).put("download", download).put("total", total)
        .put("expire", expire).put("supportUrl", supportUrl).put("webUrl", webUrl).put("updateHours", updateHours).put("announce", announce)

    companion object {
        fun of(j: JSONObject?): SubInfo = if (j == null) SubInfo() else SubInfo(j.optString("title"), j.optLong("upload"), j.optLong("download"),
            j.optLong("total"), j.optLong("expire"), j.optString("supportUrl"), j.optString("webUrl"), j.optInt("updateHours"), j.optString("announce"))

        /** ``header`` returns a header's value by its lower-case name, or null. */
        fun parse(header: (String) -> String?): SubInfo {
            val info = header("subscription-userinfo").orEmpty().split(";").mapNotNull { part ->
                val (k, v) = part.split("=", limit = 2).takeIf { it.size == 2 } ?: return@mapNotNull null
                k.trim().lowercase() to (v.trim().toDoubleOrNull()?.toLong() ?: 0L)
            }.toMap()
            return SubInfo(
                title = decode(header("profile-title")).take(80),
                upload = info["upload"] ?: 0, download = info["download"] ?: 0, total = info["total"] ?: 0, expire = info["expire"] ?: 0,
                supportUrl = link(header("support-url")), webUrl = link(header("profile-web-page-url")),
                updateHours = header("profile-update-interval")?.trim()?.toIntOrNull()?.coerceIn(0, 168) ?: 0,
                announce = decode(header("announce")).take(500),
            )
        }

        /** «base64:…» values are decoded (titles with emoji and Cyrillic come this way). */
        fun decode(value: String?): String {
            val v = value?.trim().orEmpty()
            if (!v.startsWith("base64:")) return v
            return runCatching { String(java.util.Base64.getMimeDecoder().decode(v.removePrefix("base64:")), Charsets.UTF_8) }.getOrDefault("").trim()
        }

        /** Only https:// and tg:// links open from the card. */
        private fun link(value: String?): String = value?.trim().orEmpty().takeIf { it.startsWith("https://") || it.startsWith("tg://") }.orEmpty()

        fun bytes(value: Long): String {
            if (value < 1024) return "$value B"
            val units = listOf("KB", "MB", "GB", "TB")
            var v = value.toDouble() / 1024; var i = 0
            while (v >= 1024 && i < units.size - 1) { v /= 1024; i++ }
            return String.format(java.util.Locale.ROOT, if (v >= 100) "%.0f %s" else "%.2f %s", v, units[i])
        }
    }
}
