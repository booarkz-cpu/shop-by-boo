package shop.corgi.client.vpn

import org.junit.Assert.assertEquals
import org.junit.Test

class SessionTest {
    @Test fun sessionCountsSecondsAndTraffic() {
        val s = Session(startedAt = 10_000).add(100, 2_000).add(50, 1_000)
        assertEquals(50L, s.upSpeed)
        assertEquals(1_000L, s.downSpeed)
        assertEquals(150L, s.upTotal)
        assertEquals(3_000L, s.downTotal)
        assertEquals(65L, s.seconds(75_999))
        assertEquals(0L, Session().seconds(75_999))
        assertEquals(0L, Session(startedAt = 10_000).seconds(5_000))
    }
}
