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

    /**
     * v1.9.6: whether the release manifest is asked again. Every 3 hours at most: a day-long pause hid a release that came
     * out after the morning check until the next day. A remembered update that is not newer than the installed app
     * (it has just been installed) does not count.
     */
    fun checkDue(now: Long, last: Long, force: Boolean = false): Boolean = force || last <= 0L || now - last >= CHECK_MS || now < last

    /** v1.9.6: the remembered update, only while it is still newer than the installed version. */
    fun stillNewer(cached: Update?, current: Int): Update? = cached?.takeIf { it.versionCode > current }

    /**
     * v1.9.6: the background job downloads the APK (about 150 MB) by itself only off a metered network; on mobile data it
     * shows «Доступна версия», and a tap downloads and installs it.
     */
    fun downloadInBackground(metered: Boolean): Boolean = !metered

    const val DAY_MS = 86_400_000L
    const val CHECK_MS = 3 * 3_600_000L

    /** How often the background job runs (any network). */
    const val JOB_MS = 6 * 3_600_000L
}
