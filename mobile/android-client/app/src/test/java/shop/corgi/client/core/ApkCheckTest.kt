package shop.corgi.client.core

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApkCheckTest {
    @Test fun onlyTheExactFileIsInstalledAndOnceADay() {
        val file = File.createTempFile("client", ".apk").apply { writeText("abc") }
        val sum = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assertEquals(sum, ApkCheck.sha256(file))
        assertTrue(ApkCheck.matches(file, sum.uppercase()))
        assertFalse(ApkCheck.matches(file, "0".repeat(64)))
        assertFalse("an empty file never matches", ApkCheck.matches(File.createTempFile("empty", ".apk"), sum))
        assertFalse(ApkCheck.matches(File("/nonexistent.apk"), sum))
        assertFalse(ApkCheck.due(now = ApkCheck.DAY_MS, last = 1))
        assertTrue(ApkCheck.due(now = ApkCheck.DAY_MS + 1, last = 1))
        assertTrue(ApkCheck.due(now = 5, last = 4, force = true))
    }

    /** v1.9.7: the background job installs by itself wherever the system can do it silently, a working VPN included. */
    @Test fun installsItselfAlsoUnderAWorkingVpn() {
        assertTrue(ApkCheck.installNow(sdk = 31))
        assertTrue(ApkCheck.installNow(sdk = 36))
        assertFalse("before Android 12 the system always asks", ApkCheck.installNow(sdk = 30))
        assertTrue("the tunnel comes back after the update", ApkCheck.resumeAfterUpdate(flagged = true, tunNeedsPermission = false))
        assertFalse(ApkCheck.resumeAfterUpdate(flagged = false, tunNeedsPermission = false))
        val withoutPermission = ApkCheck.resumeAfterUpdate(flagged = true, tunNeedsPermission = true)
        assertFalse("without the VPN permission nothing starts silently", withoutPermission)
    }
}
