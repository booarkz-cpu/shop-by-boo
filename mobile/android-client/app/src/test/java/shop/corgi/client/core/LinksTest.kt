package shop.corgi.client.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class LinksTest {
    private val reality = "vless://11111111-2222-3333-4444-555555555555@nl.example.com:443?type=tcp&security=reality&pbk=PUBKEY&sid=ab12&sni=www.example.com&fp=chrome&flow=xtls-rprx-vision#%F0%9F%87%B3%F0%9F%87%B1%20Netherlands"

    @Test fun vlessReality() {
        val s = Links.parse(reality)!!
        assertEquals("🇳🇱 Netherlands", s.name)
        assertEquals("nl.example.com", s.host); assertEquals(443, s.port)
        val stream = s.outbound.getJSONObject("streamSettings")
        assertEquals("reality", stream.getString("security"))
        assertEquals("PUBKEY", stream.getJSONObject("realitySettings").getString("publicKey"))
        assertEquals("xtls-rprx-vision", s.outbound.getJSONObject("settings").getJSONArray("vnext").getJSONObject(0).getJSONArray("users").getJSONObject(0).getString("flow"))
    }

    @Test fun vmessWs() {
        val json = JSONObject().put("v", "2").put("ps", "DE").put("add", "de.example.com").put("port", "8443").put("id", "uuid").put("net", "ws")
            .put("path", "/ray").put("host", "cdn.example.com").put("tls", "tls")
        val s = Links.parse("vmess://" + Base64.getEncoder().encodeToString(json.toString().toByteArray()))!!
        val stream = s.outbound.getJSONObject("streamSettings")
        assertEquals("ws", stream.getString("network")); assertEquals("/ray", stream.getJSONObject("wsSettings").getString("path"))
        assertEquals("cdn.example.com", stream.getJSONObject("tlsSettings").getString("serverName"))
        assertEquals(8443, s.port)
    }

    @Test fun trojanShadowsocksSocksWireguard() {
        assertEquals("p@ss", Links.parse("trojan://p%40ss@t.example.com:443?sni=t.example.com#T")!!.outbound.getJSONObject("settings")
            .getJSONArray("servers").getJSONObject(0).getString("password"))
        val userinfo = Base64.getUrlEncoder().withoutPadding().encodeToString("chacha20-ietf-poly1305:secret".toByteArray())
        val ss = Links.parse("ss://$userinfo@ss.example.com:8388#SS")!!
        assertEquals("chacha20-ietf-poly1305", ss.outbound.getJSONObject("settings").getJSONArray("servers").getJSONObject(0).getString("method"))
        val old = Links.parse("ss://" + Base64.getEncoder().encodeToString("aes-256-gcm:pw@1.2.3.4:999".toByteArray()) + "#Old")!!
        assertEquals("1.2.3.4", old.host); assertEquals(999, old.port)
        val socks = Links.parse("socks://dXNlcjpwYXNz@10.1.1.1:1080#S")!!
        assertEquals("user", socks.outbound.getJSONObject("settings").getJSONArray("servers").getJSONObject(0).getJSONArray("users").getJSONObject(0).getString("user"))
        val wg = Links.parse("wireguard://PRIVKEY@wg.example.com:51820?publickey=PUBKEY&address=10.7.0.2/32,fd00::2/128&reserved=1,2,3&mtu=1420#WG")!!
        assertEquals("wg.example.com", wg.host); assertEquals(51820, wg.port)
        assertEquals(3, wg.outbound.getJSONObject("settings").getJSONArray("reserved").length())
    }

    @Test fun subscriptionBodies() {
        val body = Base64.getEncoder().encodeToString("$reality\nhysteria2://x@h.example.com:443#H\ngarbage\n".toByteArray())
        val (servers, skipped) = Links.parseBody(body)
        assertEquals(1, servers.size); assertEquals(1, skipped)
        assertEquals(1, Links.parseBody(reality).first.size)
        assertNull(runCatching { Links.parse("vless://nohost") }.getOrNull())
    }
}
