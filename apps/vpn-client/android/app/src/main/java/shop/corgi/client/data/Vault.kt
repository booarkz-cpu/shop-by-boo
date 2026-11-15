package shop.corgi.client.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * v1.10.0: subscription links, servers and the local proxy's password are kept encrypted with a key of the Android
 * Keystore (AES-256-GCM; the key never leaves the device and cannot be exported). A copy of the app's files — a root
 * backup, a forensic dump — no longer gives the subscriptions away.
 *
 * Values written by older versions are plain: they are read as they are and re-saved encrypted. If the Keystore is
 * not available on a device, values stay plain (the app keeps working as before).
 */
internal object Vault {
    private const val ALIAS = "corgi_client_store_v1"
    private const val PREFIX = "ks1:"

    /** raw stored value -> plain text of the last one opened: the Keystore is asked once per change, not per read. */
    @Volatile private var opened: Pair<String, String>? = null

    fun isSealed(stored: String): Boolean = stored.startsWith(PREFIX)

    /** The value to store: encrypted, or [plain] itself when the Keystore refuses. */
    fun seal(plain: String): String = runCatching {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val data = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        val stored = PREFIX + Base64.encodeToString(cipher.iv + data, Base64.NO_WRAP)
        opened = stored to plain
        stored
    }.getOrDefault(plain)

    /** The plain text of a stored value; a plain (old) value comes back as it is; null when it cannot be opened. */
    fun open(stored: String): String? {
        if (!isSealed(stored)) return stored
        opened?.let { if (it.first == stored) return it.second }
        return runCatching {
            val bytes = Base64.decode(stored.removePrefix(PREFIX), Base64.NO_WRAP)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, 12))
            String(cipher.doFinal(bytes, 12, bytes.size - 12), Charsets.UTF_8)
        }.getOrNull()?.also { opened = stored to it }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }
}
