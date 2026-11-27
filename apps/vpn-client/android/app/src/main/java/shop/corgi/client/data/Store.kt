package shop.corgi.client.data

import android.content.Context
import android.content.SharedPreferences
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject
import shop.corgi.client.core.Links
import shop.corgi.client.core.Profile
import shop.corgi.client.core.Server
import shop.corgi.client.core.Settings
import shop.corgi.client.core.SubInfo
import shop.corgi.client.core.Update
import shop.corgi.client.core.tr

/**
 * Profiles, the chosen server and the settings in one private SharedPreferences file (no cloud backup).
 * A failed read locks the corresponding writes so an empty stand-in cannot replace the saved bytes.
 */
class Store private constructor(private val app: Context?, private val prefs: SharedPreferences) {
    constructor(context: Context) : this(
        context.applicationContext,
        context.applicationContext.getSharedPreferences("client", 0),
    )

    /** Unit tests supply memory preferences and never touch a device Keystore. */
    internal constructor(prefs: SharedPreferences) : this(null, prefs)

    /** The last read of profiles failed. [profiles] is then empty and must not be written back. */
    @Volatile var profilesLocked: Boolean = false
        private set

    /** The proxy password or the settings record could not be trusted. Writes are refused. */
    @Volatile var settingsLocked: Boolean = false
        private set

    /** A short, non-secret reason for the last vault failure. Null when the last read succeeded. */
    @Volatile var vaultMessage: String? = null
        private set

    private fun device(): Context = app ?: error("no context")

    private fun lockProfiles(message: String) {
        profilesLocked = true
        vaultMessage = message
    }

    private fun lockSettings(message: String) {
        settingsLocked = true
        vaultMessage = message
    }

    var profiles: List<Profile>
        get() = synchronized(prefs) { readProfiles() }
        set(value) = synchronized(prefs) {
            if (profilesLocked) throw VaultUnavailable("profiles unreadable; refusing to overwrite")
            val sealed = Vault.seal(JSONArray(value.map { it.toJson() }).toString())
            prefs.edit().putString("profiles", sealed).apply()
        }

    private fun readProfiles(): List<Profile> {
        // v1.10.0: kept encrypted (Vault); a value of an older version is plain and is re-saved encrypted.
        val stored = prefs.getString("profiles", "[]") ?: "[]"
        if (stored == "[]") {
            profilesLocked = false
            return emptyList()
        }
        val text = try {
            Vault.open(stored)
        } catch (error: VaultUnavailable) {
            lockProfiles(error.message ?: "vault")
            return emptyList()
        }
        val list = try {
            JSONArray(text).let { array -> (0 until array.length()).map { Profile.of(array.getJSONObject(it)) } }
        } catch (error: Exception) {
            lockProfiles(error.message ?: "profiles")
            return emptyList()
        }
        if (!Vault.isSealed(stored)) {
            try {
                prefs.edit().putString("profiles", Vault.seal(text)).apply()
            } catch (error: VaultUnavailable) {
                // The old plaintext stays. A failed seal must not pretend the value is now encrypted.
                vaultMessage = error.message
            }
        }
        profilesLocked = false
        return list
    }

    private fun readableProfiles(): List<Profile> = readProfiles().also {
        if (profilesLocked) throw VaultUnavailable("profiles unreadable; refusing to overwrite")
    }

    var settings: Settings
        get() {
            val raw = prefs.getString("settings", null) ?: return firstSettings()
            val json = runCatching { JSONObject(raw) }.getOrNull()
            if (json == null) {
                lockSettings("settings")
                return Settings()
            }
            // v1.10.0: the local proxy's password is kept encrypted (Vault); the rest of the settings is plain.
            val pass = json.optString("proxyPass")
            when {
                Vault.isSealed(pass) -> try {
                    json.put("proxyPass", Vault.open(pass))
                    settingsLocked = false
                } catch (error: VaultUnavailable) {
                    lockSettings(error.message ?: "vault")
                    json.remove("proxyPass")
                    return Settings.of(json)
                }
                pass.isNotBlank() -> try {
                    // written by an older version: re-saved with the password encrypted, or left as it was
                    val copy = JSONObject(json.toString()).put("proxyPass", Vault.seal(pass))
                    prefs.edit().putString("settings", copy.toString()).apply()
                    settingsLocked = false
                } catch (error: VaultUnavailable) {
                    vaultMessage = error.message
                    settingsLocked = false
                }
                else -> settingsLocked = false
            }
            return Settings.of(json)
        }
        set(value) {
            if (settingsLocked) throw VaultUnavailable("settings unreadable; refusing to overwrite")
            val existingPass = prefs.getString("settings", null)?.let { raw ->
                runCatching { JSONObject(raw).optString("proxyPass") }.getOrNull().orEmpty()
            }.orEmpty()
            if (existingPass.isNotBlank() && value.proxyPass.isBlank()) {
                throw VaultUnavailable("refusing to replace a stored proxy password with an empty one")
            }
            prefs.edit().putString("settings", stored(value)).apply()
        }

    /** The settings as they are written: the local proxy's password encrypted. A failed seal throws and writes nothing. */
    private fun stored(value: Settings): String =
        value.toJson().also { json -> if (value.proxyPass.isNotBlank()) json.put("proxyPass", Vault.seal(value.proxyPass)) }.toString()

    /** First launch only: there is no settings record yet, so new credentials cannot overwrite a sealed password. */
    private fun firstSettings(): Settings {
        val fresh = Settings().copy(proxyUser = "corgi_" + random(8), proxyPass = random(16))
        return try {
            prefs.edit().putString("settings", stored(fresh)).apply()
            settingsLocked = false
            fresh
        } catch (error: VaultUnavailable) {
            vaultMessage = error.message
            settingsLocked = false
            Settings()
        }
    }

    /** The active profile id and the server in it: an index or «auto». */
    var activeProfile: String
        get() = prefs.getString("active_profile", "").orEmpty()
        set(value) {
            prefs.edit().putString("active_profile", value).putBoolean("choose_server", false).apply()
        }

    /** v1.6.0 (N10): the active server was removed — nothing is connected until the user picks another one. */
    val mustChoose: Boolean get() = prefs.getBoolean("choose_server", false)

    var activeServer: String
        get() = prefs.getString("active_server", "auto").orEmpty()
        set(value) {
            prefs.edit().putString("active_server", value).putBoolean("choose_server", false).apply()
        }

    fun active(): Profile? = profiles.firstOrNull { it.id == activeProfile } ?: profiles.firstOrNull()

    fun add(text: String): Profile {
        val debuggable = app?.let { (it.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0 } == true
        require(debuggable || !text.trim().startsWith("http://")) {
            tr("Подписка — только по https://", "Subscriptions only over https://", "Підписка — лише через https://")
        }
        val profile = Profile.fromText(text, UUID.randomUUID().toString(), System.currentTimeMillis())
        synchronized(prefs) {
            val saved = readableProfiles()
            profiles = saved + profile
            if (saved.isEmpty() || activeProfile.isBlank()) {
                activeProfile = profile.id
                activeServer = "auto"
            }
        }
        return profile
    }

    /** Removes a provider (inside [ConfigGate]); returns true when it was the active one. */
    fun remove(id: String): Boolean = removeAll(setOf(id))

    /** v1.6.0 (N10): several providers at once (multi-select). The active one gone → the user picks the next server. */
    fun removeAll(ids: Set<String>): Boolean = shop.corgi.client.core.ConfigGate.run {
        synchronized(prefs) {
            val saved = readableProfiles()
            val active = saved.firstOrNull { it.id == activeProfile } ?: saved.firstOrNull()
            val wasActive = active?.id in ids
            val remaining = saved.filterNot { it.id in ids }
            profiles = remaining
            if (wasActive) {
                activeProfile = remaining.firstOrNull()?.id.orEmpty()
                activeServer = "auto"
                if (remaining.isNotEmpty()) prefs.edit().putBoolean("choose_server", true).apply()
            }
            wasActive
        }
    }

    fun replace(profile: Profile) = synchronized(prefs) {
        profiles = readableProfiles().map { if (it.id == profile.id) profile else it }
    }

    /** Fetch off the main thread. Store instances share preferences, and never hold their lock over the network. */
    fun update(profile: Profile): Profile = shop.corgi.client.core.ConfigGate.run { updateNow(profile) }

    private fun updateNow(requested: Profile): Profile {
        if (requested.kind != "subscription") return requested
        val before = synchronized(prefs) { readableProfiles().firstOrNull { it.id == requested.id } } ?: return requested
        if (before.kind != "subscription") return before
        val fetched = fetchInto(before)
        return synchronized(prefs) {
            val saved = readableProfiles()
            val current = saved.firstOrNull { it.id == before.id } ?: return@synchronized before
            // Another refresh or restore may already have installed different servers while the request was in flight.
            // Failure counters alone do not invalidate a subsequent successful response.
            if (current.copy(error = before.error, failures = before.failures, triedAt = before.triedAt) != before) {
                return@synchronized current
            }
            val now = System.currentTimeMillis()
            val next = if (fetched.error.isBlank()) {
                fetched.copy(failures = 0, triedAt = now)
            } else {
                current.copy(error = fetched.error, failures = current.failures + 1, triedAt = now)
            }
            profiles = saved.map { if (it.id == next.id) next else it }
            next
        }
    }

    private fun fetchInto(profile: Profile): Profile = try {
        val (body, info) = fetchSubscription(profile.url)
        val configs = Links.jsonConfigs(body)
        val (servers, skipped) = if (configs == null) Links.parseBody(body) else emptyList<Server>() to 0
        require(!configs.isNullOrEmpty() || servers.isNotEmpty()) {
            tr("В подписке нет поддерживаемых серверов", "The subscription has no supported servers", "У підписці немає підтримуваних серверів")
        }
        profile.copy(
            links = servers.map { it.link },
            configs = configs.orEmpty().map { it.second },
            skipped = skipped,
            error = "",
            updatedAt = System.currentTimeMillis(),
            info = info
        )
    } catch (exc: Exception) {
        profile.copy(error = exc.message?.takeIf { it.isNotBlank() } ?: exc.javaClass.simpleName)
    }

    /** Subscriptions whose interval passed (the subscription's own «profile-update-interval» when it is shorter). */
    fun updateDue(): List<Profile> {
        val s = settings
        if (!s.autoUpdate) return emptyList()
        val now = System.currentTimeMillis()
        return profiles.filter { p ->
            val interval = shop.corgi.client.core.Backoff.interval(s.updateMinutes, p.info.updateHours)
            p.kind == "subscription" && shop.corgi.client.core.Backoff.due(now, p.updatedAt, p.triedAt, p.failures, interval)
        }.map { update(it) }
    }

    /** v1.10.1: when this subscription is updated next by itself, or null (not a subscription, or updates are off). */
    fun nextUpdate(p: Profile): Long? {
        if (p.kind != "subscription") return null
        val s = settings
        return shop.corgi.client.core.Backoff.planned(s.autoUpdate, s.updateMinutes, p.info.updateHours, p.updatedAt, p.triedAt, p.failures)
    }

    fun updateAll(): List<Profile> = profiles.filter { it.kind == "subscription" }.map { update(it) }

    /** A random id of this install, sent as «x-hwid» when the user allows it (Remnawave counts devices by it). */
    val hwid: String get() = prefs.getString("hwid", null)
        ?: UUID.randomUUID().toString().uppercase().also { prefs.edit().putString("hwid", it).apply() }

    /** Last measured delays: server link → ms (-1 — no answer). */
    var pings: Map<String, Int>
        get() = runCatching {
            JSONObject(prefs.getString("pings", "{}")!!).let { j -> j.keys().asSequence().associateWith { j.getInt(it) } }
        }.getOrDefault(emptyMap())
        set(value) {
            prefs.edit().putString("pings", JSONObject(value.mapValues { it.value }).toString()).apply()
        }

    private fun random(n: Int): String {
        val chars = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        val rnd = java.security.SecureRandom()
        return (1..n).map { chars[rnd.nextInt(chars.length)] }.joinToString("")
    }

    /**
     * Puts a backup in place of the providers and settings. Both values are sealed before any write.
     * This device keeps its own proxy login and password when that password can still be opened.
     */
    fun restore(backup: shop.corgi.client.core.Backup) = synchronized(prefs) {
        val keep = if (!settingsLocked) runCatching { settings }.getOrNull()?.takeIf { !settingsLocked } else null
        val next = if (keep != null && keep.proxyUser.isNotBlank() && keep.proxyPass.isNotBlank()) {
            backup.settings.copy(proxyUser = keep.proxyUser, proxyPass = keep.proxyPass)
        } else {
            backup.settings
        }
        val profileBytes = Vault.seal(JSONArray(backup.profiles.map { it.toJson() }).toString())
        val settingsBytes = stored(next)
        val activeId = backup.activeProfile.takeIf { id -> backup.profiles.any { it.id == id } }
            ?: backup.profiles.firstOrNull()?.id.orEmpty()
        prefs.edit()
            .putString("profiles", profileBytes)
            .putString("settings", settingsBytes)
            .putString("active_profile", activeId)
            .putString("active_server", backup.activeServer.ifBlank { "auto" })
            .apply()
        profilesLocked = false
        settingsLocked = false
        vaultMessage = null
    }

    fun backup(): shop.corgi.client.core.Backup {
        val savedProfiles = profiles
        val savedSettings = settings
        if (profilesLocked || settingsLocked) throw VaultUnavailable("vault unreadable; refusing an empty backup")
        return shop.corgi.client.core.Backup(savedProfiles, savedSettings, activeProfile, activeServer, System.currentTimeMillis())
    }

    fun newProxyCredentials() {
        if (settingsLocked) throw VaultUnavailable("settings unreadable; refusing to replace credentials")
        val current = settings
        if (settingsLocked) throw VaultUnavailable("settings unreadable; refusing to replace credentials")
        settings = current.copy(proxyUser = "corgi_" + random(8), proxyPass = random(16))
    }

    /** Everything back to a fresh install, except the profiles and this install's id. */
    fun resetSettings() {
        prefs.edit().remove("settings").remove("pings").apply()
    }

    fun geoReady(): Boolean = File(device().filesDir, "geoip.dat").length() > 0 && File(device().filesDir, "geosite.dat").length() > 0

    /** geoip.dat and geosite.dat from the URLs in the settings (https only), written atomically. */
    fun downloadGeo(onProgress: (Float) -> Unit = {}) {
        val s = settings
        val files = listOf("geoip.dat" to s.geoipUrl, "geosite.dat" to s.geositeUrl)
        val progress = shop.corgi.client.core.GeoProgress(files.size, onProgress)
        for ((i, pair) in files.withIndex()) {
            val (name, url) = pair
            require(url.startsWith("https://")) { tr("Только https://", "https:// only", "Лише https://") }
            progress.start(i)
            val tmp = File(device().filesDir, "$name.part")
            val connection = open(url)
            connection.inputStream.use { input -> tmp.outputStream().use { progress.copy(input, it, connection.contentLengthLong) } }
            require(tmp.length() > 1024) { "$name: " + tr("пустой файл", "empty file", "порожній файл") }
            tmp.renameTo(File(device().filesDir, name))
        }
        progress.finish()
    }

    /** The newer version from the latest release, or null; asked at most every 3 hours unless ``force`` (v1.9.6). */
    fun checkUpdate(force: Boolean = false): Update? {
        val now = System.currentTimeMillis()
        val current = currentVersion()
        if (!shop.corgi.client.core.ApkCheck.checkDue(now, prefs.getLong("update_checked", 0), force)) return cachedUpdate()
        val found = Update.newer(fetch(Update.MANIFEST), current)
        prefs.edit().putLong("update_checked", now).putString(
            "update",
            found?.let { "${it.versionCode}|${it.versionName}|${it.sha256}|${it.apk}" } ?: ""
        ).apply()
        return found
    }

    fun currentVersion(): Int = device().packageManager.getPackageInfo(device().packageName, 0)
        .let {
            if (android.os.Build.VERSION.SDK_INT >= 28) {
                it.longVersionCode.toInt()
            } else {
                @Suppress("DEPRECATION")
                it.versionCode
            }
        }

    /** v1.6.1 (N11): the APK of [update] in the app's cache, checked by its SHA-256 (call off the main thread). */
    fun downloadUpdate(update: Update): File {
        require(update.apk.startsWith("https://github.com/booarkz-cpu/shop-by-boo/releases/")) { "apk url" }
        val dir = File(device().cacheDir, "updates").apply { mkdirs() }
        val apk = File(dir, "corgi-lusi-client-${update.versionCode}.apk")
        if (shop.corgi.client.core.ApkCheck.matches(apk, update.sha256)) return apk
        dir.listFiles()?.forEach { it.delete() }
        val tmp = File(dir, "download.part")
        open(update.apk).inputStream.use { input -> tmp.outputStream().use { input.copyTo(it) } }
        require(shop.corgi.client.core.ApkCheck.matches(tmp, update.sha256)) {
            tr("Контрольная сумма не совпала", "Checksum mismatch", "Контрольна сума не збіглася")
        }
        tmp.renameTo(apk)
        return apk
    }

    /** The downloaded APK of the newer version, if it is there and intact. */
    fun readyUpdate(): File? = cachedUpdate()?.let { u ->
        File(File(device().cacheDir, "updates"), "corgi-lusi-client-${u.versionCode}.apk").takeIf {
            shop.corgi.client.core.ApkCheck.matches(it, u.sha256)
        }
    }

    /** v1.6.1 (N11): when the shop was last asked for a newer client (0 — never). */
    fun updateCheckedAt(): Long = prefs.getLong("update_checked", 0)

    /** v1.7.3 (N12): bytes through the VPN and direct, added to today's line of the traffic history. */
    @Synchronized
    fun addTraffic(vpn: Long, direct: Long) {
        val day = shop.corgi.client.core.TrafficHistory.day(System.currentTimeMillis())
        prefs.edit().putString("traffic_history", shop.corgi.client.core.TrafficHistory.add(trafficHistory(), day, vpn, direct)).apply()
    }

    /** v1.8.1 (N12): the hand-edited Xray JSON of Geek Mode (empty — none). */
    var geekConfig: String
        get() = prefs.getString("geek_config", "") ?: ""
        set(value) {
            prefs.edit().putString("geek_config", value).apply()
        }

    /** The config the tunnel would start with now, without Geek Mode (for «Взять текущий»). */
    fun generatedConfig(): String? {
        val profile = active() ?: return null
        val s = settings
        return when {
            profile.kind == "json" -> shop.corgi.client.core.ConfigBuilder.fromJson(profile.json, s, geoReady())
            profile.configs.isNotEmpty() -> shop.corgi.client.core.ConfigBuilder.fromJson(profile.configFor(activeServer)!!, s, geoReady())
            else -> shop.corgi.client.core.ConfigBuilder.build(profile.servers(), activeServer, s, geoReady())
        }
    }

    fun trafficHistory(): String = prefs.getString("traffic_history", "{}") ?: "{}"

    fun geoUpdatedAt(): Long = File(device().filesDir, "geosite.dat").lastModified()

    fun cachedUpdate(): Update? = prefs.getString("update", "").orEmpty().split("|").takeIf { it.size == 4 }
        ?.let { runCatching { Update(it[0].toInt(), it[1], it[2], it[3]) }.getOrNull() }
        ?.let { shop.corgi.client.core.ApkCheck.stillNewer(it, currentVersion()) }

    private fun open(url: String, subscription: Boolean = false): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = true
            connectTimeout = 15000
            readTimeout = 30000
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
        // v1.9.8: at most Capped.SUBSCRIPTION_BYTES — an endless answer no longer fills the memory.
        val body = connection.inputStream.use { shop.corgi.client.core.Capped.text(it, declared = connection.contentLengthLong) }
        return body to SubInfo.parse { name -> connection.getHeaderField(name) }
    }

    private fun fetch(url: String): String = open(url).inputStream.bufferedReader().use { it.readText() }
}
