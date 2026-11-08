package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** v1.7.1 (N12, phase 2): when to leave a dead server and where to go. */
class FailoverTest {
    @Test fun switchesOnlyAfterTheTimeoutWithoutAnswers() {
        val f = Failover(30_000)
        assertFalse(f.record(false, 0))
        assertFalse(f.record(false, 20_000))
        assertTrue(f.record(false, 30_000))
        // The count starts over after a switch.
        assertFalse(f.record(false, 40_000))
    }

    @Test fun anAnswerResetsTheCount() {
        val f = Failover(30_000)
        f.record(false, 0)
        f.record(true, 25_000)
        assertFalse(f.record(false, 40_000))
        assertFalse(f.record(false, 69_000))
        assertTrue(f.record(false, 70_000))
    }

    @Test fun theFastestOtherServer() {
        val keys = listOf("a", "b", "c", "d")
        assertEquals("2", Failover.next(keys, "0", mapOf("a" to 40, "b" to 300, "c" to 90, "d" to -1)))
        // The current one is never chosen, even when its last ping was the best.
        assertEquals("1", Failover.next(keys, "2", mapOf("c" to 10, "b" to 50, "a" to 80)))
    }

    @Test fun withoutPingsTheNextInTheList() {
        val keys = listOf("a", "b", "c")
        assertEquals("1", Failover.next(keys, "0", emptyMap()))
        assertEquals("0", Failover.next(keys, "2", mapOf("a" to -1, "b" to -1)))
    }

    @Test fun nothingToSwitchTo() {
        assertNull(Failover.next(listOf("a"), "0", emptyMap()))
        assertNull(Failover.next(listOf("a", "b"), ConfigBuilder.AUTO, emptyMap()))
    }

    @Test fun settingsKeepTheChoice() {
        val s = Settings(smartFailover = true, failoverSeconds = 45)
        assertEquals(s, Settings.of(s.toJson()))
        assertThrows(IllegalArgumentException::class.java) { Settings(failoverSeconds = 5) }
    }
}
