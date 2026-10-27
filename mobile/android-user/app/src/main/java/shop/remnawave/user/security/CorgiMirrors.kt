package shop.remnawave.user.security

import android.content.Context
import android.content.SharedPreferences
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.time.OffsetDateTime

/**
 * Domain rotation: when the shop's API address is blocked the app moves to a reserve address by itself.
 *
 * The shop publishes a signed list (GET /api/public/mirrors, ECDSA P-256). The app remembers the shop's
 * key from the address the customer signed in to (trust on first use) and from then on accepts reserve
 * addresses — from the shop or from bootstrap copies such as a GitHub Gist — only with a valid signature.
 * The session token stays bound to the home address: only the network origin changes.
 */
object CorgiMirrors {
    private var prefs: SharedPreferences? = null
    private var lastFailover = 0L

    fun init(context: Context) { prefs = context.applicationContext.getSharedPreferences("corgi_mirrors", 0) }

    private fun key(home: String, name: String) = "$name|$home"
    private fun get(home: String, name: String) = prefs?.getString(key(home, name), null).orEmpty()
    private fun put(home: String, vararg values: Pair<String, String>) {
        val edit = prefs?.edit() ?: return
        values.forEach { (name, value) -> edit.putString(key(home, name), value) }
        edit.apply()
    }

    /** Origin to send requests for [home] to: the home address or the reserve one in use. */
    fun resolve(home: String): String = get(home, "active").ifBlank { home }

    /** Verified payload of a signed document, or null. [expected] is the remembered shop key, if any. */
    fun verify(document: JSONObject, expected: String?): JSONObject? = try {
        val keyText = document.getString("key")
        if (!expected.isNullOrBlank() && keyText != expected) null
        else {
            val public = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Base64.decode(keyText, Base64.NO_WRAP)))
            val check = Signature.getInstance("SHA256withECDSA")
            check.initVerify(public)
            check.update(document.getString("payload").toByteArray(Charsets.UTF_8))
            if (!check.verify(Base64.decode(document.getString("signature"), Base64.NO_WRAP))) null
            else JSONObject(document.getString("payload")).takeIf { OffsetDateTime.parse(it.getString("expires_at")).isAfter(OffsetDateTime.now()) }
        }
    } catch (_: Exception) { null }

    private fun fetch(url: String): JSONObject? = try {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 7000; readTimeout = 7000; instanceFollowRedirects = true
            setRequestProperty("Accept", "application/json")
        }
        connection.connect()
        CorgiTrust.verify(connection)
        if (connection.responseCode !in 200..299) null
        else JSONObject(connection.inputStream.bufferedReader().use { it.readText().take(64 * 1024) })
    } catch (_: Exception) { null }

    /** Sites the shop asks to send around the VPN together with Russian sites (signed list, latest shop). */
    fun direct(context: Context): List<String> = try {
        val list = JSONArray(context.getSharedPreferences("corgi_mirrors", 0).getString("direct", "[]") ?: "[]")
        (0 until list.length()).map { list.getString(it) }.filter { Regex("^[a-z0-9.-]{3,253}$").matches(it) }
    } catch (_: Exception) { emptyList() }

    private fun remember(home: String, payload: JSONObject) {
        prefs?.edit()?.putString("direct", (payload.optJSONArray("direct") ?: JSONArray()).toString())?.apply()
        put(home, "mirrors" to (payload.optJSONArray("mirrors") ?: JSONArray()).toString(),
            "bootstrap" to (payload.optJSONArray("bootstrap") ?: JSONArray()).toString(),
            "shop" to payload.optString("shop"))
    }

    /** After a successful answer: refresh the reserve list and return home once home works again. */
    fun learn(home: String) {
        if (home.isBlank()) return
        val doc = fetch("$home/api/public/mirrors")
        val known = get(home, "key")
        if (doc != null) {
            val payload = verify(doc, known.ifBlank { null }) ?: return
            if (known.isBlank()) put(home, "key" to doc.getString("key"))
            remember(home, payload)
            put(home, "active" to "")
            return
        }
        val active = get(home, "active")
        if (active.isNotBlank() && known.isNotBlank()) fetch("$active/api/public/mirrors")?.let { verify(it, known) }?.let { remember(home, it) }
    }

    /** The current origin does not answer: find a reserve address that proves it is this shop. */
    @Synchronized
    fun failover(home: String, failed: String): String? {
        val known = get(home, "key").ifBlank { return null }
        val now = System.currentTimeMillis()
        val current = resolve(home)
        if (current != failed) return current
        if (now - lastFailover < 30_000) return null
        lastFailover = now
        val candidates = linkedSetOf<String>()
        fun add(list: String) = try { JSONArray(list).let { a -> for (i in 0 until a.length()) candidates.add(a.getString(i).trimEnd('/')) } } catch (_: Exception) { }
        add(get(home, "mirrors"))
        candidates.add(home)
        try {
            val sources = JSONArray(get(home, "bootstrap").ifBlank { "[]" })
            for (i in 0 until sources.length()) {
                val payload = fetch(sources.getString(i))?.let { verify(it, known) } ?: continue
                remember(home, payload)
                add(payload.optJSONArray("mirrors")?.toString() ?: "[]")
            }
        } catch (_: Exception) { }
        for (candidate in candidates) {
            if (candidate == failed || !candidate.startsWith("https://")) continue
            val payload = fetch("$candidate/api/public/mirrors")?.let { verify(it, known) } ?: continue
            remember(home, payload)
            put(home, "active" to if (candidate == home) "" else candidate)
            return candidate
        }
        return null
    }
}
