package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BackoffTest {
    private val minute = 60_000L
    private val hour = 60 * minute

    @Test fun theDelayDoublesAndStopsAtSixHours() {
        assertEquals(0L, Backoff.delay(0))
        assertEquals(15 * minute, Backoff.delay(1))
        assertEquals(30 * minute, Backoff.delay(2))
        assertEquals(hour, Backoff.delay(3))
        assertEquals(4 * hour, Backoff.delay(5))
        assertEquals(6 * hour, Backoff.delay(6))
        assertEquals(6 * hour, Backoff.delay(500))
    }

    @Test fun aHealthySubscriptionFollowsItsInterval() {
        val updated = 1_000_000L
        assertFalse(Backoff.due(updated + 59 * minute, updated, updated, 0, hour))
        assertTrue(Backoff.due(updated + hour, updated, updated, 0, hour))
        assertEquals(updated + hour, Backoff.next(updated, updated, 0, hour))
    }

    @Test fun afterFailuresTheServerIsLeftAlone() {
        val updated = 0L
        val tried = 10 * hour // the interval passed long ago, the last try failed here
        assertFalse(Backoff.due(tried + 14 * minute, updated, tried, 1, hour))
        assertTrue(Backoff.due(tried + 15 * minute, updated, tried, 1, hour))
        assertFalse(Backoff.due(tried + 59 * minute, updated, tried, 3, hour))
        assertTrue(Backoff.due(tried + hour, updated, tried, 3, hour))
        assertEquals(tried + 6 * hour, Backoff.next(updated, tried, 9, hour))
    }

    @Test fun profileRemembersFailuresAndOldProfilesLoad() {
        val p = Profile("a", "A", "subscription", url = "https://sub.example/x", failures = 3, triedAt = 77L)
        val back = Profile.of(p.toJson())
        assertEquals(3, back.failures)
        assertEquals(77L, back.triedAt)
        val old = Profile.of(org.json.JSONObject("""{"id":"b","name":"B","kind":"subscription","url":"https://sub.example/y"}"""))
        assertEquals(0, old.failures)
        assertEquals(0L, old.triedAt)
    }
}
