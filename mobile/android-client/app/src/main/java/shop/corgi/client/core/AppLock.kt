package shop.corgi.client.core

/**
 * v1.8.2 (N12, phase 3): App Lock — the app opens only after the fingerprint, the face or the phone's PIN / pattern /
 * password (the system's own prompt; the app keeps no PIN of its own). After an unlock it stays open while used and
 * for [GRACE_MS] after leaving it, so a quick switch to another app does not ask again.
 */
object AppLock {
    const val GRACE_MS = 30_000L

    /** Locked when the switch is on and the app was never unlocked or was left more than [GRACE_MS] ago. */
    fun locked(enabled: Boolean, unlockedAt: Long, leftAt: Long, now: Long): Boolean {
        if (!enabled) return false
        if (unlockedAt <= 0L) return true
        if (leftAt <= unlockedAt) return false // still in the app since the unlock
        return now - leftAt > GRACE_MS
    }
}
