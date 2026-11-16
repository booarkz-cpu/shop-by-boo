package shop.corgi.client.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import shop.corgi.client.core.Profile

/** v1.10.0: subscriptions and the local proxy's password on the device are encrypted with a key of the Android Keystore. */
@RunWith(AndroidJUnit4::class)
class VaultTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val prefs get() = context.getSharedPreferences("client", 0)

    @Before fun clean() {
        prefs.edit().clear().commit()
        Vault.cipher = Vault.androidCipher
    }

    @After fun restoreCipher() {
        Vault.cipher = Vault.androidCipher
    }

    @Test fun aValueComesBackAndIsNotReadableWhenStored() {
        val stored = Vault.seal("vless://secret-uuid@host:443#Дом")
        assertTrue(Vault.isSealed(stored))
        assertFalse(stored.contains("secret-uuid"))
        assertEquals("vless://secret-uuid@host:443#Дом", Vault.open(stored))
        assertNotEquals("every write has its own nonce", stored, Vault.seal("vless://secret-uuid@host:443#Дом"))
        assertEquals("a value of an older version is read as it is", "[]", Vault.open("[]"))
        try {
            Vault.open(stored.dropLast(4) + "AAAA")
            fail("tampered ciphertext must not open")
        } catch (error: VaultUnavailable) {
            assertFalse(error.message.orEmpty().contains("secret-uuid"))
        }
    }

    @Test fun aFailedSealDoesNotReturnPlaintext() {
        Vault.cipher = object : VaultCipher {
            override fun encrypt(plain: String): String = throw VaultUnavailable("seal down")
            override fun decrypt(stored: String): String = throw VaultUnavailable("open down")
        }
        try {
            val returned = Vault.seal("vless://secret-uuid@host:443")
            fail("seal returned $returned")
        } catch (error: VaultUnavailable) {
            assertFalse(error.message.orEmpty().contains("secret-uuid"))
        }
    }

    @Test fun unreadableProfilesAndPasswordAreNotReplaced() {
        val store = Store(context)
        store.profiles = listOf(Profile("a", "Home", "subscription", url = "https://sub.example/secret-token"))
        val password = store.settings.proxyPass
        val profiles = prefs.getString("profiles", "")!!
        val settings = prefs.getString("settings", "")!!
        Vault.cipher = object : VaultCipher {
            override fun encrypt(plain: String): String = throw VaultUnavailable("seal down")
            override fun decrypt(stored: String): String = throw VaultUnavailable("open down")
        }
        val again = Store(context)
        assertTrue("profiles stay unread", again.profiles.isEmpty() && again.profilesLocked)
        val opened = again.settings
        assertTrue("password stays unread", opened.proxyPass.isEmpty() && again.settingsLocked)
        assertEquals(profiles, prefs.getString("profiles", ""))
        assertEquals(settings, prefs.getString("settings", ""))
        try {
            again.add("https://evil.example/new")
            fail("add replaced unreadable profiles")
        } catch (_: VaultUnavailable) {
            assertEquals(profiles, prefs.getString("profiles", ""))
        }
        try {
            again.newProxyCredentials()
            fail("credentials were regenerated")
        } catch (_: VaultUnavailable) {
            assertEquals(settings, prefs.getString("settings", ""))
            assertFalse(prefs.getString("settings", "")!!.contains(password))
        }
    }

    @Test fun profilesAreStoredEncryptedAndOldOnesAreMoved() {
        val store = Store(context)
        store.profiles = listOf(Profile("a", "Home", "subscription", url = "https://sub.example/secret-token"))
        assertFalse(prefs.getString("profiles", "")!!.contains("secret-token"))
        assertEquals("https://sub.example/secret-token", Store(context).profiles.single().url)

        // written by 1.9.x: plain JSON — still read, and encrypted from then on
        val plain = org.json.JSONArray().put(
            Profile("b", "Old", "subscription", url = "https://old.example/plain-token").toJson()
        ).toString()
        prefs.edit().putString("profiles", plain).commit()
        assertEquals("https://old.example/plain-token", Store(context).profiles.single().url)
        Thread.sleep(300) // the re-save is asynchronous (apply)
        val after = prefs.getString("profiles", "")!!
        assertTrue(Vault.isSealed(after))
        assertFalse(after.contains("plain-token"))
        assertEquals("https://old.example/plain-token", Store(context).profiles.single().url)
    }

    @Test fun theProxyPasswordIsStoredEncryptedAndTheRestOfTheSettingsIsPlain() {
        val store = Store(context)
        val made = store.settings // the first read makes the login and the password
        assertTrue(made.proxyPass.isNotBlank())
        val raw = org.json.JSONObject(prefs.getString("settings", "{}")!!)
        assertTrue(Vault.isSealed(raw.getString("proxyPass")))
        assertFalse(raw.toString().contains(made.proxyPass))
        assertEquals(made.proxyUser, raw.getString("proxyUser"))
        assertEquals(made.proxyPass, Store(context).settings.proxyPass)
        store.settings = made.copy(mtu = 1400)
        assertEquals(made.proxyPass, Store(context).settings.proxyPass)
        assertEquals(1400, Store(context).settings.mtu)
    }
}
