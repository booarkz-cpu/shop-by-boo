package shop.corgi.client.core

import java.io.ByteArrayInputStream
import java.io.InputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CappedTest {
    @Test fun anOrdinarySubscriptionIsReadWhole() {
        val body = "vless://id@host:443#Сервер\n".repeat(500)
        assertEquals(body, Capped.text(ByteArrayInputStream(body.toByteArray())))
        assertEquals("", Capped.text(ByteArrayInputStream(ByteArray(0))))
        val exact = ByteArray(64) { 'a'.code.toByte() }
        assertEquals(64, Capped.text(ByteArrayInputStream(exact), limit = 64).length)
    }

    @Test fun anEndlessAnswerStopsAtTheLimit() {
        var served = 0L
        val endless = object : InputStream() {
            override fun read(): Int {
                served++
                return 'x'.code
            }
            override fun read(b: ByteArray, off: Int, len: Int): Int {
                b.fill('x'.code.toByte(), off, off + len)
                served += len
                return len
            }
        }
        val failure = runCatching { Capped.text(endless, limit = 100_000) }.exceptionOrNull()
        assertTrue(failure is Capped.TooLarge)
        assertTrue("stopped soon after the limit, read $served", served <= 100_000 + 16 * 1024)
        assertTrue(failure!!.message!!.isNotBlank())
    }

    @Test fun aDeclaredLengthOverTheLimitIsRefusedBeforeReading() {
        var touched = false
        val body = object : InputStream() {
            override fun read(): Int {
                touched = true
                return -1
            }
        }
        assertTrue(runCatching { Capped.text(body, limit = 10, declared = 11) }.exceptionOrNull() is Capped.TooLarge)
        assertEquals(false, touched)
        assertEquals("", Capped.text(body, limit = 10, declared = 10))
    }
}
