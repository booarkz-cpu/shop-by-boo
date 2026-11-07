package shop.corgi.client.vpn

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Test

class SessionAndStreakTest {
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

    @Test fun streakIsConsecutiveDaysEndingTodayOrYesterday() {
        val today = LocalDate.of(2026, 11, 7)
        val days = (0L..2L).map { today.minusDays(it) }.toSet() + today.minusDays(5)
        assertEquals(3, Streak.count(days, today))
        assertEquals(2, Streak.count(days - today, today), "today without a connection yet keeps yesterday's streak")
        assertEquals(0, Streak.count(days, today.plusDays(2)), "a day without a connection ends it")
        assertEquals(0, Streak.count(emptySet(), today))
    }

    @Test fun oldDaysAreDropped() {
        val today = LocalDate.of(2026, 11, 7)
        val kept = Streak.with(setOf(today.minusDays(500), today.minusDays(1)), today)
        assertEquals(setOf(today.minusDays(1), today), kept)
    }

    private fun assertEquals(expected: Int, actual: Int, message: String) =
        org.junit.Assert.assertEquals(message, expected.toLong(), actual.toLong())
}
