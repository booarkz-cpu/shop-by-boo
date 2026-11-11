package shop.remnawave.user.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** v3.6.0: the app's own update check against the manifest of the latest shop release. */
class AppUpdateTest {
    private val sha = "a".repeat(64)
    private val apk = "https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android.apk"
    private fun manifest(code: Int = 3700, name: String = "3.7.0", hash: String = sha, url: String = apk) =
        """{"versionCode":$code,"versionName":"$name","sha256":"$hash","apk":"$url"}"""

    @Test fun newerVersionIsOffered() {
        val update = AppUpdate.newer(manifest(), 3600)!!
        assertEquals(AppUpdate(3700, "3.7.0", sha, apk), update)
        assertNull(AppUpdate.newer(manifest(3600, "3.6.0"), 3600))   // the same version
        assertNull(AppUpdate.newer(manifest(3500, "3.5.0"), 3600))   // an older release is never offered
    }

    @Test fun manifestFromAnotherPlaceIsRejected() {
        for (bad in listOf(
            manifest(url = "https://example.com/corgi-lusi-android.apk"),
            manifest(url = "https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.apk"),   // another app
            manifest(hash = "abc"), manifest(code = 0), manifest(name = "3.7"), "{}", "not json"
        )) assertThrows(bad, Exception::class.java) { AppUpdate.parse(bad) }
    }

    @Test fun storeInstallsAreLeftToTheStore() {
        assertTrue(AppUpdate.fromStore("com.android.vending"))
        assertTrue(AppUpdate.fromStore("ru.vk.store"))
        assertFalse(AppUpdate.fromStore(null))                                  // installed from a file
        assertFalse(AppUpdate.fromStore("com.google.android.packageinstaller"))
    }

    @Test fun onceADayAndNotAfterLater() {
        assertTrue(AppUpdate.due(AppUpdate.DAY, 0))
        assertFalse(AppUpdate.due(AppUpdate.DAY + 5, AppUpdate.DAY))
        assertTrue(AppUpdate.due(10, 500))                                      // the clock went back: check again
        val found = AppUpdate.parse(manifest())
        assertEquals(found, AppUpdate.offer(found, 3600))
        assertNull(AppUpdate.offer(found, 3700))                                // «Позже» for this version
        assertNull(AppUpdate.offer(null, 0))
        assertTrue(AppUpdate.MANIFEST.endsWith("/releases/latest/download/corgi-lusi-android.json"))
    }
}
