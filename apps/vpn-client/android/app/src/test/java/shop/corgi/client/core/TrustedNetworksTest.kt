package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import shop.corgi.client.core.TrustedNetworks.Action

/** v1.7.2 (N12, phase 2): the tunnel pauses at home and comes back elsewhere — only if it was paused by the feature. */
class TrustedNetworksTest {
    private val home = listOf("Home", "Dacha 5G")

    @Test fun pausesOnATrustedWifi() {
        assertEquals(Action.PAUSE, TrustedNetworks.decide("Home", home, vpnOn = true, pausedByUs = false))
        assertEquals(Action.NONE, TrustedNetworks.decide("Home", home, vpnOn = false, pausedByUs = true))
    }

    @Test fun comesBackElsewhereOnlyAfterItsOwnPause() {
        assertEquals(Action.RESUME, TrustedNetworks.decide(null, home, vpnOn = false, pausedByUs = true))
        assertEquals(Action.RESUME, TrustedNetworks.decide("Cafe", home, vpnOn = false, pausedByUs = true))
        // Switched off by the user — stays off.
        assertEquals(Action.NONE, TrustedNetworks.decide("Cafe", home, vpnOn = false, pausedByUs = false))
        assertEquals(Action.NONE, TrustedNetworks.decide("Cafe", home, vpnOn = true, pausedByUs = false))
    }

    @Test fun withoutTrustedNetworksNothingHappens() {
        assertEquals(Action.NONE, TrustedNetworks.decide("Home", emptyList(), vpnOn = true, pausedByUs = false))
    }

    @Test fun theSsidAsAndroidGivesIt() {
        assertEquals("Home", TrustedNetworks.clean("\"Home\""))
        assertNull(TrustedNetworks.clean("<unknown ssid>"))
        assertNull(TrustedNetworks.clean(null))
        assertNull(TrustedNetworks.clean("\"\""))
        assertTrue(TrustedNetworks.valid("Dacha 5G"))
        assertFalse(TrustedNetworks.valid("a".repeat(33)))
    }

    @Test fun settingsKeepTheList() {
        val s = Settings(trustedWifi = home)
        assertEquals(s, Settings.of(s.toJson()))
        assertThrows(IllegalArgumentException::class.java) { Settings(trustedWifi = List(21) { "n$it" }) }
        assertThrows(IllegalArgumentException::class.java) { Settings(trustedWifi = listOf("bad\nname")) }
    }
}
