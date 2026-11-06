package shop.remnawave.user.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** Stage 19, C3: the customer's rules and TLS fragmentation in the configs the engine really starts. */
class TuningTest {
    private fun server(i: Int, security: String) = VpnServer("Server $i", JSONObject().put("tag", "proxy-$i").put("protocol", "vless")
        .put("streamSettings", JSONObject().put("network", "tcp").put("security", security)))

    private fun rules(config: JSONObject): List<JSONObject> = config.getJSONObject("routing").getJSONArray("rules").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }

    private fun outbound(config: JSONObject, tag: String): JSONObject? = config.getJSONArray("outbounds").let { a ->
        (0 until a.length()).map { a.getJSONObject(it) }.firstOrNull { it.optString("tag") == tag }
    }

    @Test fun typedLinesBecomeXrayMatches() {
        assertEquals("domain:example.com", RouteRule.normalize("  Example.COM "))
        assertEquals("domain:example.com", RouteRule.normalize("https://example.com/path"))
        assertEquals("full:api.example.com", RouteRule.normalize("full:api.example.com"))
        assertEquals("keyword:ads", RouteRule.normalize("keyword:ads"))
        assertEquals("10.0.0.0/8", RouteRule.normalize("10.0.0.0/8"))
        assertEquals("2001:db8::/32", RouteRule.normalize("2001:db8::/32"))
        for (bad in listOf("", "   ", "two words", "geosite:ru", "geoip:ru", "ext:x.dat:y", "regexp:([", "domain:", "x".repeat(201))) {
            assertThrows(bad, IllegalArgumentException::class.java) { RouteRule.normalize(bad) }
        }
        assertThrows(IllegalArgumentException::class.java) { RouteRule("domain:x", "redirect") }
    }

    @Test fun rulesComeAfterTheAppsOwnAndBeforeTheCatchAll() {
        val tuning = Tuning(listOf(RouteRule("domain:bank.example", "direct"), RouteRule("keyword:ads", "block"),
            RouteRule("domain:video.example", "proxy"), RouteRule("203.0.113.0/24", "direct")))
        val config = JSONObject(XrayEngine.config(listOf(server(0, "reality"), server(1, "tls")), "Server 1", bypassRussian = true, tuning = tuning))
        val list = rules(config)
        assertEquals(listOf("direct", "direct", "direct", "block", "proxy-1", "direct", "proxy-1"), list.map { it.optString("outboundTag") })
        assertEquals("domain:bank.example", list[2].getJSONArray("domain").getString(0))
        assertEquals("203.0.113.0/24", list[5].getJSONArray("ip").getString(0))
        assertEquals("blackhole", outbound(config, "block")!!.getString("protocol"))
    }

    @Test fun throughVpnFollowsTheAutomaticChoice() {
        val config = JSONObject(XrayEngine.config(listOf(server(0, "tls"), server(1, "tls")), "", bypassRussian = false,
            tuning = Tuning(listOf(RouteRule("domain:video.example", "proxy")))))
        val list = rules(config)
        assertEquals("auto", list[1].getString("balancerTag"))
        assertEquals("auto", list.last().getString("balancerTag"))
    }

    @Test fun fragmentationSplitsOnlyTlsServers() {
        val config = JSONObject(XrayEngine.config(listOf(server(0, "reality"), server(1, "tls")), "Server 1", false,
            tuning = Tuning(fragment = true, fragmentPackets = "1-3")))
        assertFalse(outbound(config, "proxy-0")!!.getJSONObject("streamSettings").has("sockopt"))
        assertEquals(Tuning.FRAGMENT, outbound(config, "proxy-1")!!.getJSONObject("streamSettings").getJSONObject("sockopt").getString("dialerProxy"))
        val fragment = outbound(config, Tuning.FRAGMENT)!!.getJSONObject("settings").getJSONObject("fragment")
        assertEquals("1-3", fragment.getString("packets"))
        assertEquals(Tuning.LENGTH, fragment.getString("length"))
        // Off: nothing changes.
        val plain = JSONObject(XrayEngine.config(listOf(server(1, "tls")), "", false))
        assertNull(outbound(plain, Tuning.FRAGMENT))
        assertFalse(outbound(plain, "proxy-1")!!.getJSONObject("streamSettings").has("sockopt"))
    }

    @Test fun remnawaveJsonGetsRulesBeforeItsOwnRouting() {
        val remnawave = JSONObject()
            .put("outbounds", JSONArray()
                .put(JSONObject().put("tag", "proxy").put("protocol", "vless").put("streamSettings", JSONObject().put("security", "tls")))
                .put(JSONObject().put("tag", "direct").put("protocol", "freedom"))
                .put(JSONObject().put("tag", "block").put("protocol", "blackhole")))
            .put("routing", JSONObject().put("rules", JSONArray()
                .put(JSONObject().put("type", "field").put("domain", JSONArray().put("domain:bank.example")).put("outboundTag", "proxy"))
                .put(JSONObject().put("type", "field").put("network", "tcp,udp").put("outboundTag", "proxy"))))
        val tuning = Tuning(listOf(RouteRule("domain:bank.example", "direct"), RouteRule("keyword:tracker", "block")), fragment = true)
        val config = JSONObject(XrayEngine.fromJson(remnawave.toString(), bypassRussian = false, tuning = tuning))
        val list = rules(config)
        assertEquals(listOf("corgi-direct", "direct", "block", "proxy", "proxy"), list.map { it.optString("outboundTag") })
        assertEquals(Tuning.FRAGMENT, outbound(config, "proxy")!!.getJSONObject("streamSettings").getJSONObject("sockopt").getString("dialerProxy"))
    }

    @Test fun storedSettingsSurviveAndBadEntriesAreDropped() {
        val tuning = Tuning(listOf(RouteRule("domain:a.example", "direct")), fragment = true, fragmentPackets = "1-5")
        assertEquals(tuning, Tuning.of(JSONObject(tuning.toJson().toString())))
        val damaged = JSONObject().put("rules", JSONArray().put(JSONObject().put("match", "domain:b").put("action", "teleport"))
            .put(JSONObject().put("match", "domain:c").put("action", "block"))).put("fragmentPackets", "everything")
        val read = Tuning.of(damaged)
        assertEquals(listOf(RouteRule("domain:c", "block")), read.rules)
        assertEquals("tlshello", read.fragmentPackets)
        val replaced = tuning.withRule(RouteRule("domain:a.example", "block"))
        assertEquals(listOf(RouteRule("domain:a.example", "block")), replaced.rules)
        assertTrue(replaced.without("domain:a.example").rules.isEmpty())
    }
}
