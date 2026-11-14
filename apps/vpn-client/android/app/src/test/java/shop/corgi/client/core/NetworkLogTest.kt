package shop.corgi.client.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import shop.corgi.client.core.NetworkLog.Route

/** v1.7.4 (N12, phase 2): the live network log from Xray's access log. */
class NetworkLogTest {
    private val lines = listOf(
        "2026/11/08 10:00:01.123456 from 172.19.0.2:40000 accepted tcp:www.youtube.com:443 [tun-in -> proxy-0]",
        "2026/11/08 10:00:02.000001 from 172.19.0.2:40001 accepted tcp:gosuslugi.ru:443 [tun-in -> direct]",
        "2026/11/08 10:00:03.5 from 172.19.0.2:40002 accepted udp:ads.example.com:443 [tun-in -> block]",
        "2026/11/08 10:00:04.5 from 172.19.0.2:53000 accepted udp:1.1.1.1:53 [tun-in -> dns-out]",
        "2026/11/08 10:00:05.5 from 127.0.0.1:5000 accepted tcp:[2a00:1450::8]:443 [socks-in >> auto]",
        "2026/11/08 10:00:06 [Info] app/dns: UDP:1.1.1.1:53 got answer: example.com. TypeA -> [93.184.215.14] 12ms",
        "garbage"
    )

    @Test fun parsesTheRouteOfEveryConnection() {
        val e = NetworkLog.parse(lines[0])!!
        assertEquals("10:00:01", e.time)
        assertEquals("www.youtube.com", e.host)
        assertEquals(443, e.port)
        assertEquals(Route.PROXY, e.route)
        assertEquals(Route.DIRECT, NetworkLog.parse(lines[1])!!.route)
        assertEquals(Route.BLOCK, NetworkLog.parse(lines[2])!!.route)
        assertEquals(Route.DNS, NetworkLog.parse(lines[3])!!.route)
        val v6 = NetworkLog.parse(lines[4])!!
        assertEquals("2a00:1450::8", v6.host)
        assertEquals(Route.PROXY, v6.route)
        assertNull(NetworkLog.parse(lines[5]))
        assertNull(NetworkLog.parse(lines[6]))
    }

    @Test fun newestFirstWithFilters() {
        val all = NetworkLog.entries(lines)
        assertEquals(5, all.size)
        assertEquals("2a00:1450::8", all.first().host)
        assertEquals(listOf("ads.example.com"), NetworkLog.entries(lines, Route.BLOCK).map { it.host })
        assertEquals(listOf("gosuslugi.ru"), NetworkLog.entries(lines, query = "GOSUSLUGI").map { it.host })
        assertEquals(2, NetworkLog.entries(lines, limit = 2).size)
    }

    @Test fun theAccessLogIsOnOnlyWithTheSwitch() {
        val off = JSONObject("{}").also { ConfigBuilder.extras(it, Settings(), "/x/xray.log", "/x/access.log") }
        assertFalse(off.getJSONObject("log").has("access"))
        val on = JSONObject("{}").also {
            ConfigBuilder.extras(it, Settings(networkLog = true, logLevel = "none"), "/x/xray.log", "/x/access.log")
        }
        assertEquals("/x/access.log", on.getJSONObject("log").getString("access"))
        assertTrue(on.getJSONObject("log").getBoolean("dnsLog"))
        assertEquals(Settings(networkLog = true), Settings.of(Settings(networkLog = true).toJson()))
    }
}
