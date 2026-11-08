package shop.corgi.client.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import shop.corgi.client.core.Links
import shop.corgi.client.core.Profile
import shop.corgi.client.core.Settings
import shop.corgi.client.core.SubInfo
import shop.corgi.client.core.Update
import shop.corgi.client.core.tr
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
        get() = Settings.of(prefs.getString("settings", null)?.let { runCatching { JSONObject(it) }.getOrNull() }).let { s ->
            // The local proxy's login and password: random on the first use, changed only by «Сбросить логин/пароль».
            if (s.proxyUser.isNotBlank() && s.proxyPass.isNotBlank()) s
            else s.copy(proxyUser = "corgi_" + random(8), proxyPass = random(16)).also { prefs.edit().putString("settings", it.toJson().toString()).apply() }
        }
        set(value) { prefs.edit().putString("settings", value.toJson().toString()).apply() }

    /** The active profile id and the server in it: an index or «auto». */
    var activeProfile: String
        get() = prefs.getString("active_profile", "").orEmpty()
        set(value) { prefs.edit().putString("active_profile", value).putBoolean("choose_server", false).apply() }

    /** v1.6.0 (N10): the active server was removed — nothing is connected until the user picks another one. */
    val mustChoose: Boolean get() = prefs.getBoolean("choose_server", false)

    var activeServer: String
        get() = prefs.getString("active_server", "auto").orEmpty()
        set(value) { prefs.edit().putString("active_server", value).putBoolean("choose_server", false).apply() }

    fun active(): Profile? = profiles.firstOrNull { it.id == activeProfile } ?: profiles.firstOrNull()

    fun add(text: String): Profile {
        val debuggable = (app.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
        require(debuggable || !text.trim().startsWith("http://")) { tr("Подписка — только по https://", "Subscriptions only over https://", "Підписка — лише через https://") }
        val profile = Profile.fromText(text, UUID.randomUUID().toString(), System.currentTimeMillis())
        profiles = profiles + profile
        if (profiles.size == 1 || activeProfile.isBlank()) { activeProfile = profile.id; activeServer = "auto" }
        return profile
    }

    /** Removes a provider (inside [ConfigGate]); returns true when it was the active one. */
    fun remove(id: String): Boolean = removeAll(setOf(id))

    /** v1.6.0 (N10): several providers at once (multi-select). The active one gone → the user picks the next server. */
    fun removeAll(ids: Set<String>): Boolean = shop.corgi.client.core.ConfigGate.run {
        val wasActive = active()?.id in ids
        profiles = profiles.filterNot { it.id in ids }
        if (wasActive) {
            activeProfile = profiles.firstOrNull()?.id.orEmpty()
            activeServer = "auto"
            if (profiles.isNotEmpty()) prefs.edit().putBoolean("choose_server", true).apply()
        }
        wasActive
    }

    fun replace(profile: Profile) { profiles = profiles.map { if (it.id == profile.id) profile else it } }

    /** Downloads a subscription now (call off the main thread). Keeps the previous servers when it fails. */
    fun update(profile: Profile): Profile = shop.corgi.client.core.ConfigGate.run { updateNow(profile) }

    private fun updateNow(profile: Profile): Profile {
        if (profile.kind != "subscription") return profile
        val updated = try {
            val (body, info) = fetchSubscription(profile.url)
            // Remnawave answers some clients with Xray JSON instead of share links: both are understood.
            val configs = Links.jsonConfigs(body)
            if (configs != null) {
                val updated = if (configs.isEmpty()) profile.copy(error = tr("В подписке нет поддерживаемых серверов", "The subscription has no supported servers", "У підписці немає підтримуваних серверів"), updatedAt = System.currentTimeMillis())
                    else profile.copy(configs = configs.map { it.second }, links = emptyList(), skipped = 0, error = "", updatedAt = System.currentTimeMillis(), info = info)
                replace(updated)
                return updated
            }
            val (servers, skipped) = Links.parseBody(body)
            if (servers.isEmpty()) profile.copy(error = tr("В подписке нет поддерживаемых серверов", "The subscription has no supported servers", "У підписці немає підтримуваних серверів"), updatedAt = System.currentTimeMillis())
            else profile.copy(links = servers.map { it.link }, configs = emptyList(), skipped = skipped, error = "", updatedAt = System.currentTimeMillis(), info = info)
        } catch (exc: Exception) {
            profile.copy(error = exc.message ?: exc.javaClass.simpleName)
        }
        replace(updated)
        return updated
    }

    /** Subscriptions whose interval passed (the subscription's own «profile-update-interval» when it is shorter). */
    fun updateDue(): List<Profile> {
        val s = settings
        if (!s.autoUpdate) return emptyList()
        val now = System.currentTimeMillis()
        return profiles.filter { p ->
            val minutes = if (p.info.updateHours > 0) minOf(s.updateMinutes, p.info.updateHours * 60) else s.updateMinutes
            p.kind == "subscription" && now - p.updatedAt >= minutes * 60_000L
        }.map { update(it) }
    }

    fun updateAll(): List<Profile> = profiles.filter { it.kind == "subscription" }.map { update(it) }

    /** A random id of this install, sent as «x-hwid» when the user allows it (Remnawave counts devices by it). */
    val hwid: String get() = prefs.getString("hwid", null) ?: UUID.randomUUID().toString().uppercase().also { prefs.edit().putString("hwid", it).apply() }

    /** Last measured delays: server link → ms (-1 — no answer). */
    var pings: Map<String, Int>
        get() = runCatching { JSONObject(prefs.getString("pings", "{}")!!).let { j -> j.keys().asSequence().associateWith { j.getInt(it) } } }.getOrDefault(emptyMap())
        set(value) { prefs.edit().putString("pings", JSONObject(value.mapValues { it.value }).toString()).apply() }

    private fun random(n: Int): String {
        val chars = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        val rnd = java.security.SecureRandom()
        return (1..n).map { chars[rnd.nextInt(chars.length)] }.joinToString("")
    }

    /** Puts a backup in place of the providers and settings; this device keeps its own proxy login and password. */
    fun restore(backup: shop.corgi.client.core.Backup) {
        val mine = settings
        profiles = backup.profiles
        settings = backup.settings.copy(proxyUser = mine.proxyUser, proxyPass = mine.proxyPass)
        activeProfile = backup.activeProfile.takeIf { id -> backup.profiles.any { it.id == id } } ?: backup.profiles.firstOrNull()?.id.orEmpty()
        activeServer = backup.activeServer.ifBlank { "auto" }
    }

    fun backup(): shop.corgi.client.core.Backup = shop.corgi.client.core.Backup(profiles, settings, activeProfile, activeServer, System.currentTimeMillis())

    fun newProxyCredentials() { settings = settings.copy(proxyUser = "corgi_" + random(8), proxyPass = random(16)) }

    /** Everything back to a fresh install, except the profiles and this install's id. */
    fun resetSettings() { prefs.edit().remove("settings").remove("pings").apply() }

    fun geoReady(): Boolean = File(app.filesDir, "geoip.dat").length() > 0 && File(app.filesDir, "geosite.dat").length() > 0

    /** geoip.dat and geosite.dat from the URLs in the settings (https only), written atomically. */
    fun downloadGeo(onProgress: (Float) -> Unit = {}) {
        val s = settings
        val files = listOf("geoip.dat" to s.geoipUrl, "geosite.dat" to s.geositeUrl)
        val progress = shop.corgi.client.core.GeoProgress(files.size, onProgress)
        for ((i, pair) in files.withIndex()) {
            val (name, url) = pair
            require(url.startsWith("https://")) { tr("Только https://", "https:// only", "Лише https://") }
            progress.start(i)
            val tmp = File(app.filesDir, "$name.part")
            val connection = open(url)
            connection.inputStream.use { input -> tmp.outputStream().use { progress.copy(input, it, connection.contentLengthLong) } }
            require(tmp.length() > 1024) { "$name: " + tr("пустой файл", "empty file", "порожній файл") }
            tmp.renameTo(File(app.filesDir, name))
        }
        progress.finish()
    }

    /** The newer version from the latest release, or null; checked at most once a day unless ``force``. */
    fun checkUpdate(force: Boolean = false): Update? {
        val now = System.currentTimeMillis()
        if (!force && now - prefs.getLong("update_checked", 0) < 86_400_000L) return cachedUpdate()
        val current = app.packageManager.getPackageInfo(app.packageName, 0).let { if (android.os.Build.VERSION.SDK_INT >= 28) it.longVersionCode.toInt() else @Suppress("DEPRECATION") it.versionCode }
        val found = Update.newer(fetch(Update.MANIFEST), current)
        prefs.edit().putLong("update_checked", now).putString("update", found?.let { "${it.versionCode}|${it.versionName}|${it.sha256}|${it.apk}" } ?: "").apply()
        return found
    }

    /** v1.6.1 (N11): the APK of [update] in the app's cache, checked by its SHA-256 (call off the main thread). */
    fun downloadUpdate(update: Update): File {
        require(update.apk.startsWith("https://github.com/booarkz-cpu/shop-by-boo/releases/")) { "apk url" }
        val dir = File(app.cacheDir, "updates").apply { mkdirs() }
        val apk = File(dir, "corgi-lusi-client-${update.versionCode}.apk")
        if (shop.corgi.client.core.ApkCheck.matches(apk, update.sha256)) return apk
        dir.listFiles()?.forEach { it.delete() }
        val tmp = File(dir, "download.part")
        open(update.apk).inputStream.use { input -> tmp.outputStream().use { input.copyTo(it) } }
        require(shop.corgi.client.core.ApkCheck.matches(tmp, update.sha256)) { tr("Контрольная сумма не совпала", "Checksum mismatch", "Контрольна сума не збіглася") }
        tmp.renameTo(apk)
        return apk
    }

    /** The downloaded APK of the newer version, if it is there and intact. */
    fun readyUpdate(): File? = cachedUpdate()?.let { u ->
        File(File(app.cacheDir, "updates"), "corgi-lusi-client-${u.versionCode}.apk").takeIf { shop.corgi.client.core.ApkCheck.matches(it, u.sha256) }
    }

    /** v1.6.1 (N11): when the shop was last asked for a newer client (0 — never). */
    fun updateCheckedAt(): Long = prefs.getLong("update_checked", 0)

    /** v1.7.3 (N12): bytes through the VPN and direct, added to today's line of the traffic history. */
    @Synchronized
    fun addTraffic(vpn: Long, direct: Long) {
        val day = shop.corgi.client.core.TrafficHistory.day(System.currentTimeMillis())
        prefs.edit().putString("traffic_history", shop.corgi.client.core.TrafficHistory.add(trafficHistory(), day, vpn, direct)).apply()
    }

    fun trafficHistory(): String = prefs.getString("traffic_history", "{}") ?: "{}"

    fun geoUpdatedAt(): Long = File(app.filesDir, "geosite.dat").lastModified()

    fun cachedUpdate(): Update? = prefs.getString("update", "").orEmpty().split("|").takeIf { it.size == 4 }
        ?.let { Update(it[0].toInt(), it[1], it[2], it[3]) }

    private fun open(url: String, subscription: Boolean = false): HttpURLConnection = (URL(url).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = true; connectTimeout = 15000; readTimeout = 30000
        val s = settings
        // Remnawave and most panels answer v2ray-style clients with base64 share links or Xray JSON.
        setRequestProperty("User-Agent", if (subscription) s.userAgent else Settings.DEFAULT_AGENT)
        if (subscription && s.sendHwid) {
            setRequestProperty("x-hwid", hwid)
            setRequestProperty("x-device-os", "Android")
            setRequestProperty("x-ver-os", android.os.Build.VERSION.RELEASE.orEmpty())
            setRequestProperty("x-device-model", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim().take(64))
        }
        if (responseCode !in 200..299) throw IllegalStateException("HTTP $responseCode")
    }

    private fun fetchSubscription(url: String): Pair<String, SubInfo> {
        val connection = open(url, subscription = true)
        val body = connection.inputStream.bufferedReader().use { it.readText() }
        return body to SubInfo.parse { name -> connection.getHeaderField(name) }
    }

    private fun fetch(url: String): String = open(url).inputStream.bufferedReader().use { it.readText() }
}
