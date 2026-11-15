package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Test

class VerifyTest {
    @Test fun connectedOnlyAfterAnAnswer() {
        assertEquals(Verify.CHECKING, Verify.state(false, 0))
        assertEquals(Verify.CHECKING, Verify.state(false, Verify.WARN_MS - 1))
        assertEquals(Verify.ON, Verify.state(true, 0))
        assertEquals(Verify.ON, Verify.state(true, 60_000))
    }

    @Test fun aSilentServerGivesAWarningNotADisconnect() {
        assertEquals(Verify.NO_ANSWER, Verify.state(false, Verify.WARN_MS))
        assertEquals(Verify.NO_ANSWER, Verify.state(false, 10 * 60_000L))
        assertEquals("the first answer after the warning connects", Verify.ON, Verify.state(true, 10 * 60_000L))
    }

    @Test fun checksAreFrequentAtFirstAndRareAfterTheWarning() {
        assertEquals(Verify.FAST_MS, Verify.pause(0))
        assertEquals(Verify.SLOW_MS, Verify.pause(Verify.WARN_MS))
    }
}
