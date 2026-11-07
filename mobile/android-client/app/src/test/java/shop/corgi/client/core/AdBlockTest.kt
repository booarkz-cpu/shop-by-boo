package shop.corgi.client.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** v1.5.0: «Блокировка рекламы» on the main screen is a real routing rule, first of all, in every routing mode. */
class AdBlockTest {
    private val server = Links.parse("vless://u@a.example.com:443?security=tls&sni=a.example.com#A")!!

    private fun firstRule(s: Settings, geo: Boolean): JSONObject =
        JSONObject(ConfigBuilder.build(listOf(server), "0", s, geo)).getJSONObject("routing").getJSONArray("rules").getJSONObject(0)

    @Test fun adsGoToTheBlockOutboundFirst() {
        for (routing in Settings.ROUTING) {
            val rule = firstRule(Settings(routing = routing, adBlock = true), geo = true)
            assertEquals(routing, ConfigBuilder.AD_LIST, rule.getJSONArray("domain").getString(0))
            assertEquals(routing, "block", rule.getString("outboundTag"))
        }
    }

    @Test fun withoutGeoFilesTheConfigStaysValid() {
        val raw = ConfigBuilder.build(listOf(server), "0", Settings(adBlock = true), geo = false)
        assertFalse(raw.contains(ConfigBuilder.AD_LIST))
        assertFalse(ConfigBuilder.needsGeo(raw))
    }

    @Test fun offByDefaultAndKeptInSettings() {
        assertFalse(Settings().adBlock)
        assertFalse(ConfigBuilder.build(listOf(server), "0", Settings(), geo = true).contains(ConfigBuilder.AD_LIST))
        assertTrue(Settings.of(Settings(adBlock = true).toJson()).adBlock)
        assertFalse(Settings.of(JSONObject().put("adBlock", false)).adBlock)
    }
}
