package shop.remnawave.user.security

import android.content.Context
import android.util.Base64
import com.google.android.gms.tasks.Tasks
import org.json.JSONObject
import shop.remnawave.user.BuildConfig
import java.net.HttpURLConnection
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLPeerUnverifiedException

/**
 * Certificate pinning of the shop API and Play Integrity of sign-ins.
 *
 * Pins: base64 SHA-256 of the SubjectPublicKeyInfo of the server certificate or of its CA
 * (`-Pcorgi.pins=...` or CORGI_PINS, comma separated), checked for the host of the baked shop
 * address (corgi.shop_url) before any request body or session token leaves the phone.
 * Keep a backup pin (the next key or the CA) so a certificate renewal does not lock users out.
 */
object CorgiTrust {
    private val pins: Set<String> = BuildConfig.CERT_PINS.split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
    private val pinnedHost: String = try { URI(BuildConfig.SHOP_URL).host?.lowercase().orEmpty() } catch (_: Exception) { "" }
    @Volatile var appContext: Context? = null

    val pinning: Boolean get() = pins.isNotEmpty() && pinnedHost.isNotEmpty()

    /** Call after connect(): throws when the pinned host does not present a pinned key. */
    fun verify(connection: HttpURLConnection) {
        if (!pinning || connection !is HttpsURLConnection) return
        if (connection.url.host.lowercase() != pinnedHost) return
        val digest = MessageDigest.getInstance("SHA-256")
        val presented = connection.serverCertificates.map { Base64.encodeToString(digest.digest(it.publicKey.encoded), Base64.NO_WRAP) }
        if (presented.none { it in pins }) {
            connection.disconnect()
            throw SSLPeerUnverifiedException("Certificate pin mismatch for $pinnedHost")
        }
    }

    /**
     * Headers proving the genuine app (Play Integrity) for the native token exchange, when the
     * shop asks for them (GET /api/mobile/integrity/challenge → mode). Blocking; never throws.
     */
    fun integrityHeaders(base: String, fetch: (String) -> JSONObject): Map<String, String> {
        val context = appContext ?: return emptyMap()
        return try {
            val challenge = fetch("/api/mobile/integrity/challenge")
            val nonce = challenge.optString("nonce")
            if (challenge.optString("mode", "off") == "off" || nonce.isBlank()) return emptyMap()
            val manager = com.google.android.play.core.integrity.IntegrityManagerFactory.create(context)
            val request = com.google.android.play.core.integrity.IntegrityTokenRequest.builder().setNonce(nonce).build()
            val token = Tasks.await(manager.requestIntegrityToken(request), 15, TimeUnit.SECONDS).token()
            mapOf("X-Shop-Integrity" to token, "X-Shop-Integrity-Nonce" to nonce)
        } catch (_: Exception) {
            emptyMap() // the shop decides: «report» lets it through, «enforce» refuses
        }
    }
}
