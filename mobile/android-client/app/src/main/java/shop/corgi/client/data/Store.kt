package shop.corgi.client.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import shop.corgi.client.core.Links
import shop.corgi.client.core.Profile
import shop.corgi.client.core.Settings
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/** Profiles, the chosen server and the settings in one private SharedPreferences file (no cloud backup). */
class Store(context: Context) {
    private val app = context.applicationContext
    private val prefs = app.getSharedPreferences("client", 0)

    var profiles: List<Profile>
        get() = runCatching { JSONArray(prefs.getString("profiles", "[]")).let { a -> (0 until a.length()).map { Profile.of(a.getJSONObject(it)) } } }
            .getOrDefault(emptyList())
        set(value) { prefs.edit().putString("profiles", JSONArray(value.map { it.toJson() }).toString()).apply() }

    var settings: Settings
        get() = Settings.of(prefs.getString("settings", null)?.let { runCatching { JSONObject(it) }.getOrNull() })
        set(value) { prefs.edit().putString("settings", value.toJson().toString()).apply() }

    /** The active profile id and the server in it: an index or «auto». */
    var activeProfile: String
        get() = prefs.getString("active_profile", "").orEmpty()
        set(value) { prefs.edit().putString("active_profile", value).apply() }

    var activeServer: String
        get() = prefs.getString("active_server", "auto").orEmpty()
        set(value) { prefs.edit().putString("active_server", value).apply() }

    fun active(): Profile? = profiles.firstOrNull { it.id == activeProfile } ?: profiles.firstOrNull()

    fun add(text: String): Profile {
        val debuggable = (app.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
        require(debuggable || !text.trim().startsWith("http://")) { "Подписка — только по https://" }
        val profile = Profile.fromText(text, UUID.randomUUID().toString(), System.currentTimeMillis())
        profiles = profiles + profile
        if (profiles.size == 1 || activeProfile.isBlank()) { activeProfile = profile.id; activeServer = "auto" }
        return profile
    }

    fun remove(id: String) {
        profiles = profiles.filterNot { it.id == id }
        if (activeProfile == id) { activeProfile = profiles.firstOrNull()?.id.orEmpty(); activeServer = "auto" }
    }

    fun replace(profile: Profile) { profiles = profiles.map { if (it.id == profile.id) profile else it } }

    /** Downloads a subscription now (call off the main thread). Keeps the previous servers when it fails. */
    fun update(profile: Profile): Profile {
        if (profile.kind != "subscription") return profile
        val updated = try {
            val body = fetch(profile.url)
            val (servers, skipped) = Links.parseBody(body)
            if (servers.isEmpty()) profile.copy(error = "В подписке нет поддерживаемых серверов", updatedAt = System.currentTimeMillis())
            else profile.copy(links = servers.map { it.link }, skipped = skipped, error = "", updatedAt = System.currentTimeMillis())
        } catch (exc: Exception) {
            profile.copy(error = exc.message ?: exc.javaClass.simpleName)
        }
        replace(updated)
        return updated
    }

    fun updateDue() { profiles.filter { it.due(System.currentTimeMillis()) }.forEach { update(it) } }

    fun geoReady(): Boolean = File(app.filesDir, "geoip.dat").length() > 0 && File(app.filesDir, "geosite.dat").length() > 0

    /** geoip.dat and geosite.dat from the URLs in the settings (https only), written atomically. */
    fun downloadGeo() {
        val s = settings
        for ((name, url) in listOf("geoip.dat" to s.geoipUrl, "geosite.dat" to s.geositeUrl)) {
            require(url.startsWith("https://")) { "Только https://" }
            val tmp = File(app.filesDir, "$name.part")
            open(url).inputStream.use { input -> tmp.outputStream().use { input.copyTo(it) } }
            require(tmp.length() > 1024) { "$name: пустой файл" }
            tmp.renameTo(File(app.filesDir, name))
        }
    }

    private fun open(url: String): HttpURLConnection = (URL(url).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = true; connectTimeout = 15000; readTimeout = 30000
        // Remnawave and most panels answer v2ray-style clients with base64 share links.
        setRequestProperty("User-Agent", "v2rayNG/1.10.0 CorgiClient")
        if (responseCode !in 200..299) throw IllegalStateException("HTTP $responseCode")
    }

    private fun fetch(url: String): String = open(url).inputStream.bufferedReader().use { it.readText() }
}
