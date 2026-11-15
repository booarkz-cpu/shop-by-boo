package shop.corgi.client.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SealedTest {
    private val backup =
        Backup(listOf(Profile("a", "Дом", "subscription", url = "https://sub.example/secret-token")), Settings(), "a", "auto", 5L)
    private val plain = backup.toJson().toString(2)

    @Test fun aSealedFileOpensOnlyWithItsPassword() {
        val file = Sealed.seal(plain, "корги-люси", iterations = 1000)
        assertTrue(Sealed.isSealed(file))
        assertFalse("the link is not readable in the file", file.contains("secret-token"))
        assertFalse(file.contains("sub.example"))
        val opened = Backup.parse(Sealed.open(file, "корги-люси"))
        assertEquals("https://sub.example/secret-token", opened.profiles.single().url)
        assertTrue(runCatching { Sealed.open(file, "корги-люсі") }.exceptionOrNull() is Sealed.WrongPassword)
    }

    @Test fun aChangedFileIsRefused() {
        val j = JSONObject(Sealed.seal(plain, "password", iterations = 1000))
        val data = j.getString("data")
        j.put("data", (if (data[10] == 'A') 'B' else 'A').let { data.substring(0, 10) + it + data.substring(11) })
        assertTrue(runCatching { Sealed.open(j.toString(), "password") }.exceptionOrNull() is Sealed.WrongPassword)
    }

    @Test fun everyFileHasItsOwnSaltSoTwoCopiesDiffer() {
        val one = JSONObject(Sealed.seal(plain, "password", iterations = 1000))
        val two = JSONObject(Sealed.seal(plain, "password", iterations = 1000))
        assertNotEquals(one.getString("salt"), two.getString("salt"))
        assertNotEquals(one.getString("data"), two.getString("data"))
        assertEquals(Sealed.ITERATIONS, JSONObject(Sealed.seal(plain, "password")).getInt("iterations"))
    }

    @Test fun shortPasswordsAndPlainFiles() {
        assertTrue(runCatching { Sealed.seal(plain, "12345") }.isFailure)
        assertFalse("an ordinary backup is not taken for a sealed one", Sealed.isSealed(plain))
        assertFalse(Sealed.isSealed("not json"))
        assertEquals(1, Backup.parse(plain).profiles.size) // files without a password open as before
    }
}
