package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** v1.7.0 (N12): local DNS for direct sites, FakeDNS, domain strategy and the order of own rules. */
class DnsSettingsTest {
    private val a = Links.parse("vless://u@a.example.com:443?security=tls&sni=a.example.com#A")!!

    private fun config(s: Settings, geo: Boolean = false) = JSONObject(ConfigBuilder.build(listOf(a), "0", s, geo))

    private fun JSONArray.objects() = (0 until length()).mapNotNull { optJSONObject(it) }

    @Test fun byDefaultNothingChanges() {
        val c = config(Settings())
        val servers = c.getJSONObject("dns").getJSONArray("servers")
        assertEquals(listOf("1.1.1.1", "8.8.8.8"), (0 until servers.length()).map { servers.get(it) })
        assertFalse(c.has("fakedns"))
        assertTrue(c.getJSONArray("outbounds").objects().none { it.optString("protocol") == "dns" })
        assertEquals("AsIs", c.getJSONObject("routing").getString("domainStrategy"))
    }

    @Test fun fakeDnsAnswersTheDeviceAndSniffsItsAddresses() {
        val c = config(Settings(fakeDns = true))
        assertEquals("fakedns", c.getJSONObject("dns").getJSONArray("servers").getString(0))
        assertEquals(ConfigBuilder.FAKE_POOL, c.getJSONArray("fakedns").getJSONObject(0).getString("ipPool"))
        val tun = c.getJSONArray("inbounds").getJSONObject(0)
        assertTrue(tun.getJSONObject("sniffing").getJSONArray("destOverride").toString().contains("fakedns"))
        assertTrue(c.getJSONArray("outbounds").objects().any { it.optString("tag") == "dns-out" && it.optString("protocol") == "dns" })
        val first = c.getJSONObject("routing").getJSONArray("rules").getJSONObject(0)
        assertEquals("dns-out", first.getString("outboundTag"))
        assertEquals("53", first.getString("port"))
        // Xray's own queries carry no device inbound tag, so they do not loop back into the DNS module.
        assertTrue(first.getJSONArray("inboundTag").toString().contains("tun-in"))
    }

    @Test fun localDnsAnswersOnlyTheDirectDomains() {
        val s = Settings(
            routing = "bypass_ru",
            localDns = "77.88.8.8",
            rules = listOf(Rule("domain:bank.example", "direct"), Rule("domain:ads.example", "block"), Rule("10.1.0.0/16", "direct"))
        )
        val servers = config(s).getJSONObject("dns").getJSONArray("servers")
        val local = servers.objects().single()
        assertEquals("77.88.8.8", local.getString("address"))
        val domains = local.getJSONArray("domains").toString()
        assertTrue(domains.contains("domain:bank.example") && domains.contains("gosuslugi.ru"))
        assertFalse(domains.contains("ads.example") || domains.contains("10.1.0.0"))
        assertTrue(local.getBoolean("skipFallback"))
    }

    @Test fun localDnsWithoutDirectDomainsAddsNoServer() {
        val servers = config(Settings(routing = "global", localDns = "77.88.8.8")).getJSONObject("dns").getJSONArray("servers")
        assertTrue(servers.objects().isEmpty())
    }

    @Test fun domainStrategyOverridesTheAutomaticOne() {
        assertEquals("IPOnDemand", config(Settings(domainStrategy = "IPOnDemand")).getJSONObject("routing").getString("domainStrategy"))
        assertEquals("IPIfNonMatch", config(Settings(), geo = true).getJSONObject("routing").getString("domainStrategy"))
    }

    @Test fun ownRulesInTheBlockProxyDirectOrder() {
        val rules = listOf(Rule("domain:d.example", "direct"), Rule("domain:p.example", "proxy"), Rule("domain:b.example", "block"))
        assertEquals(listOf("block", "proxy", "direct"), ConfigBuilder.ordered(rules, "block_proxy_direct").map { it.action })
        assertEquals(rules, ConfigBuilder.ordered(rules, "written"))
        val c = config(Settings(routing = "custom", rules = rules, ruleOrder = "block_proxy_direct"))
        val tags = c.getJSONObject("routing").getJSONArray("rules").objects()
            .filter { it.optJSONArray("domain")?.toString()?.contains(".example") == true }.map { it.getString("outboundTag") }
        assertEquals(listOf("block", "proxy-0", "direct"), tags)
    }

    @Test fun settingsCheckAndKeepTheDnsChoice() {
        assertThrows(IllegalArgumentException::class.java) { Settings(localDns = "tls://1.1.1.1 ; rm") }
        assertThrows(IllegalArgumentException::class.java) { Settings(domainStrategy = "Fastest") }
        assertThrows(IllegalArgumentException::class.java) { Settings(ruleOrder = "random") }
        for (ok in listOf(
            "77.88.8.8",
            "localhost",
            "https+local://dns.yandex/dns-query",
            "tcp://1.1.1.1:53",
            "quic+local://dns.adguard.com"
        )) {
            assertEquals(ok, Settings(localDns = ok).localDns)
        }
        val s = Settings(localDns = "77.88.8.8", fakeDns = true, domainStrategy = "IPIfNonMatch", ruleOrder = "block_proxy_direct")
        assertEquals(s, Settings.of(s.toJson()))
    }
}
