package shop.corgi.client.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsAndInfoTest {
    @Test fun settingsRoundTripKeepsEveryField() {
        val s = Settings(theme = "light", materialYou = true, amoled = true, textScale = 1.2f, lang = "uk", connectStyle = "compact", vibration = false,
            autoUpdate = false, updateMinutes = 60, notifyUpdates = true, updateOnLaunch = false, pingOnLaunch = true, pingAfterUpdate = true,
            sendHwid = false, userAgent = "Happ/1.0", sort = "ping", pingMethod = "tcp", pingDisplay = "both", pingUrl = Settings.PING_URLS[1], pingTimeout = 5,
            fragment = true, fragmentPackets = "1-3", sniffing = false, routeOnly = false, blockUdp = true, idleTimeout = 600, excludedRoutes = listOf("203.0.113.0/24"))
        assertEquals(s, Settings.of(JSONObject(s.toJson().toString())))
    }

    @Test fun oneBadValueFallsBackAloneAndOldSettingsLoad() {
        val loaded = Settings.of(JSONObject("""{"theme":"neon","mtu":1400,"pingTimeout":99,"sort":"name","routing":"custom"}"""))
        assertEquals("corgi", loaded.theme)   // unknown → default
        assertEquals(1400, loaded.mtu)
        assertEquals(3, loaded.pingTimeout)
        assertEquals("name", loaded.sort)
        assertEquals("custom", loaded.routing)
        // A v1.2 file (theme «system», no new keys) keeps its theme.
        assertEquals("system", Settings.of(JSONObject("""{"theme":"system"}""")).theme)
    }

    @Test fun badInputIsRefused() {
        assertTrue(runCatching { Settings(excludedRoutes = listOf("not a cidr")) }.isFailure)
        assertTrue(runCatching { Settings(userAgent = "a\nb") }.isFailure)
        assertTrue(runCatching { Settings(updateMinutes = 7) }.isFailure)
    }

    @Test fun subscriptionHeaders() {
        val headers = mapOf("subscription-userinfo" to "upload=1073741824; download=10433211904; total=0; expire=1798761600",
            "profile-title" to "base64:" + java.util.Base64.getEncoder().encodeToString("Корги Люси 🐾".toByteArray()),
            "support-url" to "https://t.me/corgi_support", "profile-web-page-url" to "javascript:alert(1)", "profile-update-interval" to "12")
        val info = SubInfo.parse { headers[it] }
        assertEquals("Корги Люси 🐾", info.title)
        assertEquals(1073741824L + 10433211904L, info.used)
        assertEquals(0L, info.total)
        assertEquals(1798761600L, info.expire)
        assertEquals("https://t.me/corgi_support", info.supportUrl)
        assertEquals("", info.webUrl)   // only https:// and tg:// open
        assertEquals(12, info.updateHours)
        assertEquals(info, SubInfo.of(info.toJson()))
        assertTrue(SubInfo.parse { null }.empty)
        assertEquals("10.72 GB", SubInfo.bytes(11507000000))
    }

    @Test fun serverLabelsFilterAndSort() {
        val links = listOf("vless://11111111-2222-3333-4444-555555555555@nl.example.com:443?security=reality&pbk=KEY&sid=ab&type=tcp#Netherlands",
            "hysteria2://pass@hy.example.com:443?sni=hy.example.com#Alpha", "vless://11111111-2222-3333-4444-555555555555@de.example.com:443?security=tls&type=grpc#Germany")
        val servers = links.map { Links.parse(it)!! }
        assertEquals(listOf("VLESS", "TCP", "REALITY"), servers[0].labels)
        assertEquals(listOf("Hysteria2", "TLS"), servers[1].labels)
        assertEquals(listOf("VLESS", "GRPC", "TLS"), servers[2].labels)
        val pings = mapOf(Ping.key(servers[0]) to 300, Ping.key(servers[1]) to -1, Ping.key(servers[2]) to 120)
        assertEquals(listOf(2, 0, 1), ServerList.arrange(servers, "ping", pings, "", null).map { it.first })
        assertEquals(listOf(1, 2, 0), ServerList.arrange(servers, "name", pings, "", null).map { it.first })
        assertEquals(listOf(1), ServerList.arrange(servers, "default", pings, "", "Hysteria2").map { it.first })
        assertEquals(listOf(2), ServerList.arrange(servers, "default", pings, "germ", null).map { it.first })
    }

    @Test fun pingHelpers() {
        assertEquals(23, Ping.parseIcmp("64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=23.4 ms"))
        assertEquals(-1, Ping.parseIcmp("1 packets transmitted, 0 received"))
        assertEquals(listOf(0, 1, 2, 3, 3), listOf(null, 120, 500, 900, -1).map { Ping.level(it) })
        val probe = JSONObject(Ping.probeConfig(Links.parse("trojan://secret@de.example.com:443#Germany")!!))
        assertEquals("proxy", probe.getJSONArray("outbounds").getJSONObject(0).getString("tag"))
        assertFalse(probe.has("inbounds"))
    }

    @Test fun tunnelOptionsReachTheConfig() {
        val servers = listOf(Links.parse("trojan://secret@de.example.com:443?security=tls&sni=de.example.com#Germany")!!)
        val config = JSONObject(ConfigBuilder.build(servers, "0", Settings(fragment = true, fragmentPackets = "1-3", sniffing = false, blockUdp = true,
            idleTimeout = 120, excludedRoutes = listOf("203.0.113.0/24")), geo = false))
        val tun = config.getJSONArray("inbounds").getJSONObject(0)
        assertFalse(tun.getJSONObject("sniffing").getBoolean("enabled"))
        assertEquals(120, config.getJSONObject("policy").getJSONObject("levels").getJSONObject("0").getInt("connIdle"))
        val rules = config.getJSONObject("routing").getJSONArray("rules")
        assertEquals("203.0.113.0/24", rules.getJSONObject(0).getJSONArray("ip").getString(0))
        assertEquals("udp", rules.getJSONObject(1).getString("network"))
        assertEquals("block", rules.getJSONObject(1).getString("outboundTag"))
        val fragment = (0 until config.getJSONArray("outbounds").length()).map { config.getJSONArray("outbounds").getJSONObject(it) }.first { it.getString("tag") == "fragment" }
        assertEquals("1-3", fragment.getJSONObject("settings").getJSONObject("fragment").getString("packets"))
    }
}
