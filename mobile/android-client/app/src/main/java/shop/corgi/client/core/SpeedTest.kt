package shop.corgi.client.core

import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL
import javax.net.ssl.HttpsURLConnection

/**
 * v1.7.3 (N12, phase 2): the real speed of the server — a download and an upload through the running tunnel (the
 * connection's own SOCKS inbound on 127.0.0.1), to Cloudflare's speed test endpoints.
 */
object SpeedTest {
    const val DOWN_URL = "https://speed.cloudflare.com/__down?bytes="
    const val UP_URL = "https://speed.cloudflare.com/__up"
    const val DOWN_BYTES = 10_000_000
    const val UP_BYTES = 3_000_000

    data class Result(val downMbps: Double, val upMbps: Double)

    /** Megabits per second for [bytes] in [millis]; 0 for a zero time. */
    fun mbps(bytes: Long, millis: Long): Double = if (millis <= 0) 0.0 else bytes * 8.0 / 1_000_000.0 / (millis / 1000.0)

    private fun open(check: IpCheck, url: String): HttpsURLConnection {
        ExternalIp.authenticate(check)
        val proxy = Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", check.port))
        return (URL(url).openConnection(proxy) as HttpsURLConnection).apply {
            connectTimeout = 10_000
            readTimeout = 20_000
        }
    }

    /** Off the main thread; throws when the tunnel does not answer. */
    fun run(check: IpCheck, now: () -> Long = System::currentTimeMillis): Result {
        val down = open(check, DOWN_URL + DOWN_BYTES)
        var got = 0L
        val started = now()
        down.inputStream.use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                got += n
            }
        }
        val downMbps = mbps(got, now() - started)
        val up = open(check, UP_URL)
        up.requestMethod = "POST"
        up.doOutput = true
        up.setFixedLengthStreamingMode(UP_BYTES)
        val upStarted = now()
        up.outputStream.use { out ->
            val chunk = ByteArray(64 * 1024)
            var left = UP_BYTES
            while (left > 0) {
                val n = minOf(left, chunk.size)
                out.write(chunk, 0, n)
                left -= n
            }
        }
        up.responseCode
        val upMbps = mbps(UP_BYTES.toLong(), now() - upStarted)
        up.disconnect()
        return Result(downMbps, upMbps)
    }
}
