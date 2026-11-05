package shop.corgi.client.core

import org.json.JSONObject

/**
 * Update check: every shop release carries corgi-lusi-client.json next to corgi-lusi-client.apk
 * ({"versionCode": 110, "versionName": "1.1.0", "sha256": "…", "apk": "https://…/corgi-lusi-client.apk"}).
 * The app compares versionCode and offers the signed APK; Android itself checks that the signature matches.
 */
data class Update(val versionCode: Int, val versionName: String, val sha256: String, val apk: String) {
    companion object {
        const val MANIFEST = "https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.json"
        private val SHA = Regex("^[0-9a-f]{64}$")

        fun parse(text: String): Update {
            val j = JSONObject(text)
            val u = Update(j.getInt("versionCode"), j.getString("versionName"), j.getString("sha256").lowercase(), j.getString("apk"))
            require(u.versionCode > 0 && SHA.matches(u.sha256)) { "manifest" }
            require(u.apk.startsWith("https://github.com/booarkz-cpu/shop-by-boo/releases/")) { "apk url" }
            return u
        }

        /** The newer one, or null when the app is up to date. */
        fun newer(text: String, current: Int): Update? = parse(text).takeIf { it.versionCode > current }
    }
}
