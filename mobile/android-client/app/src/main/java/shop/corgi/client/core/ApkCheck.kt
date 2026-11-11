package shop.corgi.client.core

import java.io.File
import java.security.MessageDigest

/** v1.6.1 (N11): the downloaded APK is installed only when its SHA-256 is the one of the release manifest. */
object ApkCheck {
    fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    fun matches(file: File, expected: String): Boolean = file.isFile && file.length() > 0 && sha256(file) == expected.lowercase()

    /**
     * v1.9.2: whether the background job installs the downloaded update itself. An update restarts the app, so never
     * while the VPN works; before Android 12 the system always asks, and the question cannot be shown from the background.
     */
    fun installNow(sdk: Int, vpnRunning: Boolean): Boolean = sdk >= 31 && !vpnRunning

    /** Once a day at most, unless forced. */
    fun due(now: Long, last: Long, force: Boolean = false): Boolean = force || now - last >= DAY_MS

    const val DAY_MS = 86_400_000L
}
