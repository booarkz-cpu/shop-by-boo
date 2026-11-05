package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.HttpURLConnection
import java.net.URL

class UpdatesTest {
    private val sha = "a".repeat(64)
    private fun manifest(code: Int, apk: String = "https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-client.apk") =
        """{"versionCode":$code,"versionName":"1.2.0","sha256":"$sha","apk":"$apk"}"""

    @Test fun newerOnly() {
        assertEquals("1.2.0", Update.newer(manifest(120), 110)!!.versionName)
        assertNull(Update.newer(manifest(110), 110))
        assertThrows(IllegalArgumentException::class.java) { Update.parse(manifest(120, "https://evil.example.com/x.apk")) }
        assertThrows(IllegalArgumentException::class.java) { Update.parse(manifest(120).replace(sha, "zz")) }
    }

    @Test fun tvReceiverTakesOneSubscriptionByItsKey() {
        val got = mutableListOf<String>()
        val receiver = TvReceiver { got += it }
        val port = receiver.start()
        fun post(path: String, body: String): Int {
            val c = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
            c.requestMethod = "POST"; c.doOutput = true
            c.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            c.outputStream.use { it.write(body.toByteArray()) }
            return c.responseCode
        }
        assertEquals(404, post("/wrong", "text=x"))
        val page = (URL("http://127.0.0.1:$port/${receiver.key}").openConnection() as HttpURLConnection)
        assertEquals(200, page.responseCode)
        assertTrue(page.inputStream.bufferedReader().readText().contains("<form"))
        assertEquals(200, post("/${receiver.key}", "text=" + java.net.URLEncoder.encode("https://sub.example.com/abc", "UTF-8")))
        assertEquals(listOf("https://sub.example.com/abc"), got)
        Thread.sleep(1500)
        assertTrue(receiver.done)
        receiver.stop()
    }
}
