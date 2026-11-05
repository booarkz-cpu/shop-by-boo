package shop.corgi.client.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

class ProxyBackupSchemeTest {
    private val server = Links.parse("trojan://secret@de.example.com:443?security=tls&sni=de.example.com#Germany")!!

    private fun config(s: Settings) = JSONObject(ConfigBuilder.build(listOf(server), "0", s, geo = false))

    @Test fun modesAndLocalProxy() {
        val tun = config(Settings(proxyUser = "u", proxyPass = "p")).getJSONArray("inbounds")
        assertEquals(1, tun.length()); assertEquals("tun", tun.getJSONObject(0).getString("protocol"))
        val both = config(Settings(localProxy = true, proxyUser = "u", proxyPass = "p")).getJSONArray("inbounds")
        assertEquals(listOf("tun", "socks", "http"), (0 until both.length()).map { both.getJSONObject(it).getString("protocol") })
        val proxy = config(Settings(tunnelMode = "proxy", shareLan = true, proxyUser = "u", proxyPass = "p", socksPort = 2080, httpPort = 2081)).getJSONArray("inbounds")
        assertEquals(2, proxy.length())
        val socks = proxy.getJSONObject(0)
        assertEquals("0.0.0.0", socks.getString("listen")); assertEquals(2080, socks.getInt("port"))
        assertEquals("password", socks.getJSONObject("settings").getString("auth"))
        assertEquals("u", socks.getJSONObject("settings").getJSONArray("accounts").getJSONObject(0).getString("user"))
        val open = config(Settings(tunnelMode = "proxy", proxyAuth = false, httpAuth = false, proxyUser = "u", proxyPass = "p")).getJSONArray("inbounds")
        assertEquals("127.0.0.1", open.getJSONObject(0).getString("listen"))
        assertEquals("noauth", open.getJSONObject(0).getJSONObject("settings").getString("auth"))
        // Sharing to the network without a password is refused.
        assertTrue(runCatching { Settings(shareLan = true, proxyAuth = false) }.isFailure)
        assertTrue(runCatching { Settings(socksPort = 2080, httpPort = 2080) }.isFailure)
    }

    @Test fun muxNoisesLogsAndStats() {
        val c = config(Settings(mux = true, muxConcurrency = 4, fragment = true, noises = true, speedNotification = true, logLevel = "info"))
        ConfigBuilder.extras(c, Settings(speedNotification = true, logLevel = "info"), "/data/x/logs/xray.log")
        val proxy = c.getJSONArray("outbounds").getJSONObject(0)
        assertEquals(4, proxy.getJSONObject("mux").getInt("concurrency"))
        val fragment = (0 until c.getJSONArray("outbounds").length()).map { c.getJSONArray("outbounds").getJSONObject(it) }.first { it.getString("tag") == "fragment" }
        assertEquals("rand", fragment.getJSONObject("settings").getJSONArray("noises").getJSONObject(0).getString("type"))
        assertEquals("/data/x/logs/xray.log", c.getJSONObject("log").getString("error"))
        assertTrue(c.getJSONObject("policy").getJSONObject("system").getBoolean("statsOutboundUplink"))
        // Vision («flow») does not take mux.
        val vision = Links.parse("vless://11111111-2222-3333-4444-555555555555@nl.example.com:443?security=reality&pbk=KEY&sid=ab&flow=xtls-rprx-vision#NL")!!
        val row = JSONObject(vision.outbound.toString()); ConfigBuilder.mux(row, Settings(mux = true))
        assertFalse(row.has("mux"))
        val quiet = JSONObject(); ConfigBuilder.extras(quiet, Settings(speedNotification = false), "/x")
        assertEquals("none", quiet.getJSONObject("log").getString("loglevel")); assertFalse(quiet.has("stats"))
    }

    @Test fun backupRoundTripWithoutProxyCredentials() {
        val profile = Profile.fromText("trojan://secret@de.example.com:443#Germany", "p1", 1)
        val backup = Backup(listOf(profile), Settings(sort = "name", proxyUser = "corgi_x", proxyPass = "secret"), "p1", "0", 5)
        val json = backup.toJson()
        assertFalse(json.getJSONObject("settings").has("proxyPass"))
        val back = Backup.parse(backup.link())
        assertEquals(listOf(profile), back.profiles)
        assertEquals("name", back.settings.sort)
        assertEquals("", back.settings.proxyPass)
        assertEquals(listOf("Germany — 1"), back.summary())
        assertTrue(runCatching { Backup.parse("{\"format\":\"other\"}") }.isFailure)
    }

    @Test fun urlSchemes() {
        assertEquals(Scheme.Connect, Scheme.parse("corgi://connect"))
        assertEquals(Scheme.Toggle, Scheme.parse("corgi://toggle"))
        assertNull(Scheme.parse("https://example.com"))
        assertNull(Scheme.parse("corgi://format-disk"))
        val b64 = java.util.Base64.getEncoder().encodeToString("vless://x@h:1#a".toByteArray())
        assertEquals(Scheme.Import("vless://x@h:1#a"), Scheme.parse("corgi://import/$b64"))
        assertEquals(Scheme.Import("https://sub.example.com/abc"), Scheme.parse("corgi://add/https%3A%2F%2Fsub.example.com%2Fabc"))
        val rules = java.util.Base64.getUrlEncoder().encodeToString("example.com direct\ngeosite:category-ads-all block\n10.0.0.0/8".toByteArray())
        val parsed = Scheme.parse("corgi://routing/onadd/$rules") as Scheme.Rules
        assertTrue(parsed.apply)
        assertEquals(listOf(Rule("domain:example.com", "direct"), Rule("geosite:category-ads-all", "block"), Rule("10.0.0.0/8", "proxy")), parsed.rules)
        val json = java.util.Base64.getEncoder().encodeToString("""[{"match":"ru","action":"direct"}]""".toByteArray())
        assertEquals(listOf(Rule("domain:ru", "direct")), (Scheme.parse("corgi://routing/add/$json") as Scheme.Rules).rules)
    }

    @Test fun logsRotateAndExpire() {
        val dir = Files.createTempDirectory("logs").toFile()
        val logs = Logs(dir)
        logs.xray.writeText("first\nerror one\n")
        logs.rotate(hours = 1)
        assertTrue(File(logs.dir, "xray_1.log").exists()); assertFalse(logs.xray.exists())
        logs.xray.writeText("second\n"); logs.rotate(hours = 1)
        assertEquals("first\nerror one\n", File(logs.dir, "xray_2.log").readText())
        assertEquals(listOf("error one"), logs.lines(File(logs.dir, "xray_2.log"), "ERROR"))
        File(logs.dir, "xray_2.log").setLastModified(System.currentTimeMillis() - 2 * 3_600_000L)
        logs.rotate(hours = 1)
        assertFalse(File(logs.dir, "xray_2.log").exists())
        logs.app("[VPN] connect"); assertTrue(logs.files().any { it.name == "app.log" })
        logs.clear(); assertTrue(logs.files().isEmpty())
    }
}
