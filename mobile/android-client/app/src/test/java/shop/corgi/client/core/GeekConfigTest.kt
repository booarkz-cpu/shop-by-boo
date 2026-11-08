package shop.corgi.client.core

import java.util.Locale
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** v1.8.1 (N12, phase 3): Geek Mode — only a config that can start the tunnel is accepted. */
class GeekConfigTest {
    private val a = Links.parse("vless://u@a.example.com:443?security=tls&sni=a.example.com#A")!!

    @Before fun english() {
        Locale.setDefault(Locale.ENGLISH)
    }

    @Test fun theGeneratedConfigIsAcceptedAndPretty() {
        val raw = ConfigBuilder.build(listOf(a), "0", Settings(), geo = false)
        val pretty = GeekConfig.pretty(raw)
        assertTrue(pretty.contains("\n  \"outbounds\""))
        assertNull(GeekConfig.problem(pretty))
        assertEquals(JSONObject(raw).toString(), JSONObject(pretty).toString())
    }

    @Test fun brokenTextIsRefused() {
        assertNotNull(GeekConfig.problem(""))
        assertTrue(GeekConfig.problem("{ \"outbounds\": [")!!.startsWith("JSON error"))
        assertNotNull(GeekConfig.problem("{}"))
        assertNotNull(GeekConfig.problem("{\"outbounds\": []}"))
        assertNotNull(GeekConfig.problem("{\"outbounds\": [1]}"))
        assertNotNull(GeekConfig.problem("{\"outbounds\": [{\"tag\": \"x\"}]}"))
        assertNotNull(GeekConfig.problem("{\"outbounds\": [{\"protocol\": \"freedom\"}], \"routing\": {\"rules\": {}}}"))
        assertNotNull(
            GeekConfig.problem("{\"outbounds\":[{\"protocol\":\"freedom\"}],\"x\":\"" + "a".repeat(GeekConfig.MAX_LENGTH) + "\"}")
        )
        assertNull(GeekConfig.problem("{\"outbounds\": [{\"protocol\": \"freedom\"}]}"))
    }

    @Test fun settingsKeepTheSwitch() {
        assertEquals(Settings(geekMode = true), Settings.of(Settings(geekMode = true).toJson()))
        // v1.8.1: the mascot is on by default and can be turned off.
        assertTrue(Settings().mascot)
        assertEquals(Settings(mascot = false), Settings.of(Settings(mascot = false).toJson()))
    }
}
