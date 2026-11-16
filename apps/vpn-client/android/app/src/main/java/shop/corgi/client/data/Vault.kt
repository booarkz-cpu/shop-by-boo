package shop.corgi.client.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Keystore refused to seal or open a value. Callers must keep the previous bytes. */
internal class VaultUnavailable(message: String, cause: Throwable? = null) : Exception(message, cause)

/** Encrypts and decrypts one value. A failure throws; it never returns the original plaintext. */
internal interface VaultCipher {
    fun encrypt(plain: String): String

    fun decrypt(stored: String): String
}

/**
 * v1.10.0: subscription links, servers and the local proxy's password are kept encrypted with a key of the Android
 * Keystore (AES-256-GCM; the key never leaves the device and cannot be exported). A copy of the app's files — a root
 * backup, a forensic dump — no longer gives the subscriptions away.
 *
 * Values written by older versions are plain: they are read as they are and re-saved encrypted when sealing works.
 * If the Keystore refuses, sealing throws [VaultUnavailable] and the caller leaves the previous bytes in place.
 * Plaintext is never stored as a substitute for a failed encryption.
 */
internal object Vault {
    private const val ALIAS = "corgi_client_store_v1"
    const val PREFIX = "ks1:"

    /** The production cipher. Tests replace [cipher] and must restore [androidCipher]. */
    internal val androidCipher: VaultCipher = AndroidKeystoreCipher

    /** raw stored value -> plain text of the last one opened: the Keystore is asked once per change, not per read. */
    @Volatile private var opened: Pair<String, String>? = null

    @Volatile
    internal var cipher: VaultCipher = androidCipher
        set(value) {
            field = value
            opened = null
        }

    fun isSealed(stored: String): Boolean = stored.startsWith(PREFIX)

    /** The value to store. Throws [VaultUnavailable] when the Keystore (or [cipher]) refuses; never returns [plain]. */
    fun seal(plain: String): String {
        val stored = try {
            cipher.encrypt(plain)
        } catch (error: VaultUnavailable) {
            throw error
        } catch (error: Exception) {
            throw VaultUnavailable("keystore seal failed", error)
        }
        if (!isSealed(stored) || stored == plain) throw VaultUnavailable("seal refused to return plaintext")
        opened = stored to plain
        return stored
    }

    /**
     * The plain text of a stored value. A plain (old) value comes back as it is.
     * A sealed value that cannot be opened throws [VaultUnavailable] instead of looking like empty data.
     */
    fun open(stored: String): String {
        if (!isSealed(stored)) return stored
        opened?.let { if (it.first == stored) return it.second }
        val plain = try {
            cipher.decrypt(stored)
        } catch (error: VaultUnavailable) {
            throw error
        } catch (error: Exception) {
            throw VaultUnavailable("keystore open failed", error)
        }
        opened = stored to plain
        return plain
    }

    private object AndroidKeystoreCipher : VaultCipher {
        override fun encrypt(plain: String): String {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val data = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
            return PREFIX + Base64.encodeToString(cipher.iv + data, Base64.NO_WRAP)
        }

        override fun decrypt(stored: String): String {
            val bytes = Base64.decode(stored.removePrefix(PREFIX), Base64.NO_WRAP)
            if (bytes.size <= 12) throw VaultUnavailable("truncated ciphertext")
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, 12))
            return String(cipher.doFinal(bytes, 12, bytes.size - 12), Charsets.UTF_8)
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
}
