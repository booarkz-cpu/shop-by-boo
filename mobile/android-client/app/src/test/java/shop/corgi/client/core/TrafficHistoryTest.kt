package shop.corgi.client.core

import java.util.TimeZone
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** v1.7.3 (N12, phase 2): traffic by day (VPN and direct) and the speed test's arithmetic. */
class TrafficHistoryTest {
    private val utc = TimeZone.getTimeZone("UTC")

    @Test fun addsUpWithinADay() {
        var json = "{}"
        json = TrafficHistory.add(json, "2026-11-08", 1000, 10)
        json = TrafficHistory.add(json, "2026-11-08", 500, 5)
        json = TrafficHistory.add(json, "2026-11-07", 7, 0)
        assertEquals(
            listOf(TrafficHistory.Day("2026-11-07", 7, 0), TrafficHistory.Day("2026-11-08", 1500, 15)),
            TrafficHistory.read(json)
        )
    }

    @Test fun keepsNinetyDaysAndIgnoresJunk() {
        var json = "{\"bad\": [1, 2], \"2026-01-01\": \"x\"}"
        val start = 1_767_225_600_000L // 2026-01-01 UTC
        for (i in 0 until 100) json = TrafficHistory.add(json, TrafficHistory.day(start + i * 86_400_000L, utc), 1, 1)
        val days = TrafficHistory.read(json)
        assertEquals(TrafficHistory.KEEP_DAYS, days.size)
        assertEquals("2026-01-11", days.first().day)
        assertTrue(TrafficHistory.read("not json").isEmpty())
        assertThrows(IllegalArgumentException::class.java) { TrafficHistory.add("{}", "yesterday", 1, 1) }
    }

    @Test fun negativeCountersAreNotAdded() {
        val json = TrafficHistory.add("{}", "2026-11-08", -5, -1)
        assertEquals(TrafficHistory.Day("2026-11-08", 0, 0), TrafficHistory.read(json).single())
    }

    @Test fun theSeriesHasEveryDayInOrder() {
        val today = System.currentTimeMillis()
        val json = TrafficHistory.add("{}", TrafficHistory.day(today), 42, 4)
        val week = TrafficHistory.series(json, 7, today)
        assertEquals(7, week.size)
        assertEquals(42L, week.last().vpn)
        assertTrue(week.dropLast(1).all { it.vpn == 0L && it.direct == 0L })
        assertEquals(week.map { it.day }.sorted(), week.map { it.day })
    }

    @Test fun megabitsPerSecond() {
        assertEquals(80.0, SpeedTest.mbps(10_000_000, 1000), 0.001)
        assertEquals(0.0, SpeedTest.mbps(10, 0), 0.0)
    }
}
