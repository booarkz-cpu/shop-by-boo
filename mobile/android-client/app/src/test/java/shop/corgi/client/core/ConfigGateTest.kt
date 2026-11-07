package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigGateTest {
    @Test fun busyOnlyInsideAndNotifiesOnTheEdges() {
        val seen = mutableListOf<Boolean>()
        val stop = ConfigGate.listen { seen += ConfigGate.busy }
        assertFalse(ConfigGate.busy)
        val result =
            ConfigGate.run {
                assertTrue(ConfigGate.busy)
                ConfigGate.run { assertTrue(ConfigGate.busy) }
                42
            }
        assertEquals(42, result)
        assertFalse(ConfigGate.busy)
        assertEquals("one change on entering, one on leaving", listOf(true, false), seen)
        runCatching { ConfigGate.run { error("boom") } }
        assertFalse("an error frees the gate", ConfigGate.busy)
        stop()
    }
}
