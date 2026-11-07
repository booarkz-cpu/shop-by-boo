package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ExternalIpTest {
    @Test fun parseAndFlag() {
        val ip = ExternalIp.parse("""{"ip": "203.0.113.7", "country": "nl", "org": "AS1 Example"}""")!!
        assertEquals("203.0.113.7", ip.ip)
        assertEquals("🇳🇱", ip.flag)
        assertEquals("", ExternalIp("2001:db8::1", "").flag)
        assertNull(ExternalIp.parse("""{"ip": "<script>"}"""))
        assertNull(ExternalIp.parse("not json"))
    }

    @Test fun theInboundIsLocalAndAlwaysWithAPassword() {
        val check = IpCheck.random(41234)
        val inbound = check.inbound()
        assertEquals("127.0.0.1", inbound.getString("listen"))
        assertEquals(IpCheck.TAG, inbound.getString("tag"))
        assertEquals("password", inbound.getJSONObject("settings").getString("auth"))
        assertTrue(check.pass.length >= 24 && check.user != IpCheck.random(41234).user)
    }
}
