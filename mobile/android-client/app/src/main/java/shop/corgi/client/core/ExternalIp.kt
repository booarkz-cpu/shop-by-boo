package shop.corgi.client.core

import java.net.Authenticator
import java.net.InetSocketAddress
import java.net.PasswordAuthentication
import java.net.Proxy
import java.net.URL
import java.security.SecureRandom
import javax.net.ssl.HttpsURLConnection
import org.json.JSONObject

/**
 * v1.6.0 (N10): the address the internet sees after connecting, and its country. The app itself never goes through its
 * own tunnel, so the check goes through a SOCKS inbound of the running Xray on 127.0.0.1 with a login and password made
 * for this connection only; the answer of ipinfo.io gives the address and the country.
 */
data class IpCheck(val port: Int, val user: String, val pass: String) {
    companion object {
        const val TAG = "ip-check"
        private const val LETTERS = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

        fun random(port: Int): IpCheck {
            val rnd = SecureRandom()
            fun word(n: Int) = (1..n).map { LETTERS[rnd.nextInt(LETTERS.length)] }.joinToString("")
            return IpCheck(port, "ip" + word(8), word(24))
        }
    }

    /** The inbound added to the config of this connection (listens on 127.0.0.1 only, always with a password). */
    fun inbound(): JSONObject = JSONObject()
        .put("tag", TAG)
        .put("protocol", "socks")
        .put("listen", "127.0.0.1")
        .put("port", port)
        .put(
            "settings",
            JSONObject().put("auth", "password").put("udp", false)
                .put("accounts", org.json.JSONArray().put(JSONObject().put("user", user).put("pass", pass)))
        )
}

data class ExternalIp(val ip: String, val country: String) {
    /** The flag of the country: two regional indicator letters, or nothing when the country is unknown. */
    val flag: String
        get() =
            if (Regex("^[A-Z]{2}$").matches(country)) {
                country.map { String(Character.toChars(0x1F1E6 + (it - 'A'))) }.joinToString("")
            } else {
                ""
            }

    companion object {
        const val URL_INFO = "https://ipinfo.io/json"
        private val IP = Regex("^[0-9a-fA-F:.]{3,45}$")

        fun parse(text: String): ExternalIp? {
            val json = runCatching { JSONObject(text) }.getOrNull() ?: return null
            val ip = json.optString("ip")
            if (!IP.matches(ip)) return null
            return ExternalIp(ip, json.optString("country").uppercase().take(2))
        }

        /** v1.7.1 (N12): does [url] answer through the tunnel (2xx/3xx in 8 s)? For Smart Failover (off the main thread). */
        fun probe(check: IpCheck, url: String): Boolean {
            authenticate(check)
            return runCatching {
                val proxy = Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", check.port))
                val connection = URL(url).openConnection(proxy) as java.net.HttpURLConnection
                connection.connectTimeout = 8_000
                connection.readTimeout = 8_000
                connection.instanceFollowRedirects = false
                try {
                    connection.responseCode in 200..399
                } finally {
                    connection.disconnect()
                }
            }.getOrDefault(false)
        }

        private fun authenticate(check: IpCheck) {
            Authenticator.setDefault(
                object : Authenticator() {
                    override fun getPasswordAuthentication(): PasswordAuthentication? = if (requestingHost == "127.0.0.1" &&
                        requestingPort == check.port
                    ) {
                        PasswordAuthentication(check.user, check.pass.toCharArray())
                    } else {
                        null
                    }
                }
            )
        }

        /** Through the tunnel's SOCKS inbound [check]; null when there is no answer (call off the main thread). */
        fun lookup(check: IpCheck): ExternalIp? {
            authenticate(check)
            return runCatching {
                val proxy = Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", check.port))
                val connection = URL(URL_INFO).openConnection(proxy) as HttpsURLConnection
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000
                connection.setRequestProperty("Accept", "application/json")
                connection.inputStream.bufferedReader().use { parse(it.readText()) }
            }.getOrNull()
        }
    }
}
