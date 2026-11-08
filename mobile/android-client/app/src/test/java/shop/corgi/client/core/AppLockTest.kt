package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** v1.8.2 (N12, phase 3): when the app asks for the fingerprint or the phone's PIN. */
class AppLockTest {
    @Test fun offNeverLocks() {
        assertFalse(AppLock.locked(enabled = false, unlockedAt = 0, leftAt = 0, now = 1_000_000))
    }

    @Test fun locksUntilTheFirstUnlock() {
        assertTrue(AppLock.locked(enabled = true, unlockedAt = 0, leftAt = 0, now = 1))
    }

    @Test fun staysOpenWhileUsedAndForAShortSwitch() {
        assertFalse(AppLock.locked(true, unlockedAt = 1_000, leftAt = 0, now = 900_000))
        assertFalse(AppLock.locked(true, unlockedAt = 1_000, leftAt = 5_000, now = 5_000 + AppLock.GRACE_MS))
        assertTrue(AppLock.locked(true, unlockedAt = 1_000, leftAt = 5_000, now = 5_001 + AppLock.GRACE_MS))
    }

    @Test fun settingsKeepTheSwitch() {
        assertEquals(Settings(appLock = true), Settings.of(Settings(appLock = true).toJson()))
    }
}
