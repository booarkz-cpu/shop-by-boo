package shop.corgi.client.data

import android.content.SharedPreferences
import java.net.InetAddress
import java.net.ServerSocket
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import shop.corgi.client.core.Backup
import shop.corgi.client.core.Profile
import shop.corgi.client.core.Settings

/** Keystore failures are injected. No device and no claim that a phone lost data. */
class VaultFailureTest {
    private val cipher = MemoryCipher()
    private val prefs = MemoryPrefs()

    @Before fun install() {
        Vault.cipher = cipher
    }

    @After fun restore() {
        Vault.cipher = Vault.androidCipher
    }

    @Test fun aLateFailedRefreshKeepsTheLatestSavedServers() {
        val store = Store(prefs)
        store.settings = store.settings.copy(sendHwid = false)
        val executor = Executors.newSingleThreadExecutor()
        try {
            ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { listener ->
                listener.soTimeout = 10_000
                val stale = store.add("https://127.0.0.1:${listener.localPort}/subscription")
                val saved = stale.copy(
                    links = listOf("trojan://test-only@vpn.example.invalid:443#Selected"),
                    name = "Updated provider",
                    updatedAt = 12345,
                    failures = 3
                )
                store.activeServer = "0"
                val refresh = executor.submit<Profile> { Store(prefs).update(stale) }
                listener.accept().use {
                    listener.close()
                    store.replace(saved)
                }
                val concurrent = refresh.get(15, TimeUnit.SECONDS)
                assertEquals(saved, concurrent)
                assertEquals(saved, Store(prefs).active())

                val failed = store.update(stale)
                assertTrue(failed.error.isNotBlank())
                assertEquals(saved.failures + 1, failed.failures)
                assertTrue(failed.triedAt > saved.triedAt)
                assertEquals(saved, failed.copy(error = saved.error, failures = saved.failures, triedAt = saved.triedAt))
                assertEquals(failed, Store(prefs).active())
                assertEquals("0", store.activeServer)
            }
        } finally {
            executor.shutdownNow()
        }
    }

    @Test fun aRemovedSubscriptionIsNotWrittenBackByAnOldRefresh() {
        val store = Store(prefs)
        val removed = store.add("https://127.0.0.1:1/removed")
        val active = store.add("trojan://test-only@vpn.example.invalid:443#Remaining")
        assertTrue(store.remove(removed.id))
        val before = prefs.all.toMap()
        Store(prefs).update(removed)
        assertEquals(before, prefs.all)
        assertEquals(active, store.active())
    }

    @Test fun sealNeverReturnsPlaintext() {
        cipher.failSeal = true
        try {
            val returned = Vault.seal("vless://secret-uuid@host")
            fail("seal returned $returned")
        } catch (error: VaultUnavailable) {
            assertFalse(error.message.orEmpty().contains("secret-uuid"))
        }
        cipher.failSeal = false
        cipher.returnPlaintext = true
        try {
            Vault.seal("vless://secret-uuid@host")
            fail("plaintext was accepted as a sealed value")
        } catch (error: VaultUnavailable) {
            assertFalse(error.message.orEmpty().contains("secret-uuid"))
        }
    }

    @Test fun firstCredentialsAreNotStoredWhenSealFails() {
        cipher.failSeal = true
        val empty = MemoryPrefs()
        val created = Store(empty)
        assertTrue(created.settings.proxyPass.isEmpty())
        assertEquals(null, empty.getString("settings", null))
        assertEquals(null, empty.getString("profiles", null))
    }

    @Test fun openOfLegacyTextWorksAndTamperDoesNotLookEmpty() {
        assertEquals("[]", Vault.open("[]"))
        val sealed = Vault.seal("token")
        assertEquals("token", Vault.open(sealed))
        try {
            Vault.open("ks1:missing")
            fail("tampered value opened")
        } catch (error: VaultUnavailable) {
            assertFalse(error.message.orEmpty().contains("token"))
        }
    }

    @Test fun plaintextProfilesMigrateAndStayWhenSealFails() {
        val plain = JSONArray().put(Profile("b", "Old", "subscription", url = "https://old.example/plain-token").toJson()).toString()
        prefs.edit().putString("profiles", plain).commit()
        assertEquals("https://old.example/plain-token", Store(prefs).profiles.single().url)
        assertTrue(Vault.isSealed(prefs.getString("profiles", "")!!))
        assertFalse(prefs.getString("profiles", "")!!.contains("plain-token"))

        prefs.edit().putString("profiles", plain).commit()
        cipher.failSeal = true
        val store = Store(prefs)
        assertEquals("https://old.example/plain-token", store.profiles.single().url)
        assertFalse(store.profilesLocked)
        assertEquals(plain, prefs.getString("profiles", ""))
        try {
            store.add("https://evil.example/new")
            fail("add wrote after a failed seal")
        } catch (_: VaultUnavailable) {
            assertEquals(plain, prefs.getString("profiles", ""))
            assertFalse(prefs.getString("profiles", "")!!.contains("evil.example"))
        }
    }

    @Test fun failedOpenDoesNotWipeProfilesOrMintCredentials() {
        cipher.failSeal = false
        val store = Store(prefs)
        store.profiles = listOf(Profile("a", "Home", "subscription", url = "https://sub.example/secret-token"))
        val made = store.settings
        val profiles = prefs.getString("profiles", "")!!
        val settings = prefs.getString("settings", "")!!
        assertTrue(made.proxyPass.isNotBlank())
        assertFalse(settings.contains(made.proxyPass))

        cipher.failOpen = true
        Vault.cipher = cipher
        val again = Store(prefs)
        assertTrue(again.profiles.isEmpty() && again.profilesLocked)
        assertTrue(again.settings.proxyPass.isEmpty() && again.settingsLocked)
        assertEquals(profiles, prefs.getString("profiles", ""))
        assertEquals(settings, prefs.getString("settings", ""))
        try {
            again.add("https://evil.example/new")
            fail("add overwrote profiles")
        } catch (_: VaultUnavailable) {
            assertEquals(profiles, prefs.getString("profiles", ""))
        }
        try {
            again.replace(Profile("a", "Home", "subscription", url = "https://sub.example/other"))
            fail("replace overwrote profiles")
        } catch (_: VaultUnavailable) {
            assertEquals(profiles, prefs.getString("profiles", ""))
        }
        try {
            again.remove("a")
            fail("remove overwrote profiles")
        } catch (_: VaultUnavailable) {
            assertEquals(profiles, prefs.getString("profiles", ""))
        }
        try {
            again.newProxyCredentials()
            fail("new credentials were stored")
        } catch (_: VaultUnavailable) {
            assertEquals(settings, prefs.getString("settings", ""))
        }
        try {
            again.backup()
            fail("empty backup was produced")
        } catch (_: VaultUnavailable) {
            assertEquals(profiles, prefs.getString("profiles", ""))
        }
        try {
            again.settings = again.settings.copy(mtu = 1400)
            fail("settings were overwritten")
        } catch (_: VaultUnavailable) {
            assertEquals(settings, prefs.getString("settings", ""))
        }

        cipher.failOpen = false
        Vault.cipher = cipher
        val recovered = Store(prefs)
        assertEquals("https://sub.example/secret-token", recovered.profiles.single().url)
        assertFalse(recovered.profilesLocked)
        assertEquals(made.proxyPass, recovered.settings.proxyPass)
        assertFalse(recovered.settingsLocked)
    }

    @Test fun restoreSealsBeforeWritingAndKeepsBytesWhenSealFails() {
        val store = Store(prefs)
        store.profiles = listOf(Profile("a", "Home", "subscription", url = "https://sub.example/secret-token"))
        val profiles = prefs.getString("profiles", "")!!
        val settings = prefs.getString("settings", "")!!
        val incoming = Backup(
            listOf(Profile("n", "New", "subscription", url = "https://new.example/token")),
            Settings(proxyUser = "corgi_restore", proxyPass = "restorepass", mtu = 1400),
            "n",
            "auto",
            1
        )
        cipher.failSeal = true
        try {
            store.restore(incoming)
            fail("restore wrote while seal failed")
        } catch (_: VaultUnavailable) {
            assertEquals(profiles, prefs.getString("profiles", ""))
            assertEquals(settings, prefs.getString("settings", ""))
        }
        cipher.failSeal = false
        cipher.failOpen = true
        Vault.cipher = cipher
        val locked = Store(prefs)
        assertTrue(locked.profiles.isEmpty() && locked.profilesLocked)
        cipher.failOpen = false
        Vault.cipher = cipher
        locked.restore(incoming)
        assertFalse(locked.profilesLocked || locked.settingsLocked)
        assertEquals("https://new.example/token", Store(prefs).profiles.single().url)
        assertEquals(1400, Store(prefs).settings.mtu)
        assertTrue(Vault.isSealed(prefs.getString("profiles", "")!!))
        val savedPass = JSONObject(prefs.getString("settings", "{}")!!).getString("proxyPass")
        assertTrue(Vault.isSealed(savedPass))
        assertFalse(prefs.getString("settings", "")!!.contains("restorepass"))
    }

    @Test fun corruptProfilesStayOnDisk() {
        prefs.edit().putString("profiles", "ks1:not-json").commit()
        cipher.known["ks1:not-json"] = "not-json"
        val store = Store(prefs)
        assertTrue(store.profiles.isEmpty() && store.profilesLocked)
        assertEquals("ks1:not-json", prefs.getString("profiles", ""))
        try {
            store.profiles = emptyList()
            fail("empty list replaced corrupt profiles")
        } catch (_: VaultUnavailable) {
            assertEquals("ks1:not-json", prefs.getString("profiles", ""))
        }
    }

    private class MemoryCipher : VaultCipher {
        var failSeal = false
        var failOpen = false
        var returnPlaintext = false
        val known = mutableMapOf<String, String>()
        private var next = 0

        override fun encrypt(plain: String): String {
            if (failSeal) throw VaultUnavailable("seal down")
            if (returnPlaintext) return plain
            val stored = "ks1:${++next}"
            known[stored] = plain
            return stored
        }

        override fun decrypt(stored: String): String {
            if (failOpen) throw VaultUnavailable("open down")
            return known[stored] ?: throw VaultUnavailable("open down")
        }
    }

    private class MemoryPrefs : SharedPreferences {
        private val data = linkedMapOf<String, Any?>()

        override fun getAll(): Map<String, *> = data.toMap()
        override fun getString(key: String?, defValue: String?): String? = data[key] as? String ?: defValue
        override fun getStringSet(key: String?, defValues: MutableSet<String>?): MutableSet<String>? = defValues
        override fun getInt(key: String?, defValue: Int): Int = data[key] as? Int ?: defValue
        override fun getLong(key: String?, defValue: Long): Long = data[key] as? Long ?: defValue
        override fun getFloat(key: String?, defValue: Float): Float = data[key] as? Float ?: defValue
        override fun getBoolean(key: String?, defValue: Boolean): Boolean = data[key] as? Boolean ?: defValue
        override fun contains(key: String?): Boolean = key in data
        override fun edit(): SharedPreferences.Editor = Editor()
        override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit
        override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit

        private inner class Editor : SharedPreferences.Editor {
            private val puts = linkedMapOf<String, Any?>()
            private val removals = mutableSetOf<String>()
            private var clear = false

            override fun putString(key: String?, value: String?): SharedPreferences.Editor = apply { if (key != null) puts[key] = value }
            override fun putStringSet(key: String?, values: MutableSet<String>?): SharedPreferences.Editor = this
            override fun putInt(key: String?, value: Int): SharedPreferences.Editor = apply { if (key != null) puts[key] = value }
            override fun putLong(key: String?, value: Long): SharedPreferences.Editor = apply { if (key != null) puts[key] = value }
            override fun putFloat(key: String?, value: Float): SharedPreferences.Editor = apply { if (key != null) puts[key] = value }
            override fun putBoolean(key: String?, value: Boolean): SharedPreferences.Editor = apply { if (key != null) puts[key] = value }
            override fun remove(key: String?): SharedPreferences.Editor = apply { if (key != null) removals += key }
            override fun clear(): SharedPreferences.Editor = apply { clear = true }
            override fun commit(): Boolean {
                apply()
                return true
            }
            override fun apply() {
                if (clear) data.clear()
                removals.forEach { data.remove(it) }
                data.putAll(puts)
            }
        }
    }
}
