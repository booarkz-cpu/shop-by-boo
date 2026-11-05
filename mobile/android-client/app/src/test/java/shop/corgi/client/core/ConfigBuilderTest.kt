package shop.corgi.client.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigBuilderTest {
    private val a = Links.parse("vless://u@a.example.com:443?security=tls&sni=a.example.com#A")!!
    private val b = Links.parse("trojan://p@b.example.com:443#B")!!

    @Test fun chosenServerAndPrivateRanges() {
        val c = JSONObject(ConfigBuilder.build(listOf(a, b), "1", Settings(), geo = false))
        val rules = c.getJSONObject("routing").getJSONArray("rules")
        assertEquals("direct", rules.getJSONObject(0).getString("outboundTag"))
        assertEquals("proxy-1", rules.getJSONObject(rules.length() - 1).getString("outboundTag"))
        assertEquals("tun", c.getJSONArray("inbounds").getJSONObject(0).getString("protocol"))
        assertFalse(c.has("observatory"))
    }

    @Test fun automaticChoiceUsesTheBalancer() {
        val c = JSONObject(ConfigBuilder.build(listOf(a, b), ConfigBuilder.AUTO, Settings(routing = "global"), geo = false))
        assertTrue(c.has("observatory"))
        assertEquals("leastPing", c.getJSONObject("routing").getJSONArray("balancers").getJSONObject(0).getJSONObject("strategy").getString("type"))
    }

    @Test fun fragmentOnlyOnTls() {
        val c = JSONObject(ConfigBuilder.build(listOf(a, b), "0", Settings(fragment = true), geo = false))
        val outbounds = c.getJSONArray("outbounds")
        assertEquals("fragment", outbounds.getJSONObject(0).getJSONObject("streamSettings").getJSONObject("sockopt").getString("dialerProxy"))
        assertTrue((0 until outbounds.length()).any { outbounds.getJSONObject(it).optString("tag") == "fragment" })
    }

    @Test fun geoRulesNeedTheFiles() {
        val s = Settings(routing = "custom", rules = listOf(Rule("geosite:category-ads-all", "block"), Rule(Rule.normalize("Example.com"), "direct")))
        val without = ConfigBuilder.build(listOf(a), "0", s, geo = false)
        assertFalse(ConfigBuilder.needsGeo(without))
        assertTrue(without.contains("domain:example.com"))
        assertTrue(ConfigBuilder.needsGeo(ConfigBuilder.build(listOf(a), "0", s, geo = true)))
        assertEquals("10.0.0.0/8", Rule.normalize("10.0.0.0/8"))
        assertThrows(IllegalArgumentException::class.java) { Rule.normalize("two words") }
    }

    @Test fun fullJsonKeepsOutboundsAndReplacesInbounds() {
        val raw = """{"remarks":"Mine","inbounds":[{"protocol":"socks","port":10808}],"outbounds":[{"tag":"x","protocol":"freedom"}],"api":{}}"""
        val c = JSONObject(ConfigBuilder.fromJson(raw, Settings()))
        assertEquals(1, c.getJSONArray("inbounds").length()); assertEquals("tun", c.getJSONArray("inbounds").getJSONObject(0).getString("protocol"))
        assertFalse(c.has("api"))
        assertEquals("json", Profile.fromText(raw, "1", 0).kind)
        assertEquals("Mine", Profile.fromText(raw, "1", 0).name)
    }

    @Test fun profilesFromText() {
        assertEquals("subscription", Profile.fromText("https://sub.example.com/abc", "1", 0).kind)
        assertEquals("links", Profile.fromText("vless://u@a.example.com:443#A\ntrojan://p@b.example.com:443#B", "1", 0).kind)
        assertThrows(IllegalArgumentException::class.java) { Profile.fromText("hysteria2://x@h:1", "1", 0) }
        assertThrows(IllegalArgumentException::class.java) { Profile("1", "x", "subscription", url = "http://evil.example.com") }
        val p = Profile("1", "x", "subscription", url = "https://s.example.com", updatedAt = 0, autoUpdateHours = 12)
        assertTrue(p.due(13 * 3_600_000L)); assertFalse(p.due(1))
    }

    @Test fun settingsRoundTrip() {
        val s = Settings(routing = "custom", rules = listOf(Rule("domain:a.com", "proxy")), apps = setOf("org.x"), appsMode = "except", fragment = true)
        assertEquals(s, Settings.of(s.toJson()))
        assertEquals(Settings(), Settings.of(JSONObject().put("routing", "nonsense")))
    }
}
