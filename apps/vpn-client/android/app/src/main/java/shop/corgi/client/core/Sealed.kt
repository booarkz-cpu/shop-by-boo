package shop.corgi.client.core

import java.security.SecureRandom
import java.util.Base64
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec
import org.json.JSONObject

/**
 * v1.9.9: a backup file can be closed with a password. The file holds subscription links — whoever has it has the
 * subscriptions — so with a password it is AES-256-GCM, the key comes from the password by PBKDF2-HMAC-SHA256 with a
 * random salt. Without a password the file is written as before (and old files open as before).
 */
object Sealed {
    const val FORMAT = "corgi-client-backup-sealed"
    const val ITERATIONS = 210_000
    const val MIN_PASSWORD = 6

    class WrongPassword :
        IllegalArgumentException(
            tr("Пароль не подходит или файл повреждён", "Wrong password or a damaged file", "Пароль не підходить або файл пошкоджено")
        )

    fun isSealed(text: String): Boolean = runCatching { JSONObject(text.trim()).optString("format") == FORMAT }.getOrDefault(false)

    fun seal(text: String, password: String, random: SecureRandom = SecureRandom(), iterations: Int = ITERATIONS): String {
        require(password.length >= MIN_PASSWORD) {
            tr(
                "Пароль — не короче $MIN_PASSWORD символов",
                "The password is at least $MIN_PASSWORD characters",
                "Пароль — не коротший за $MIN_PASSWORD символів"
            )
        }
        val salt = ByteArray(16).also { random.nextBytes(it) }
        val iv = ByteArray(12).also { random.nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key(password, salt, iterations), GCMParameterSpec(128, iv))
        cipher.updateAAD(FORMAT.toByteArray(Charsets.UTF_8))
        val data = cipher.doFinal(text.toByteArray(Charsets.UTF_8))
        val b64 = Base64.getEncoder()
        return JSONObject().put("format", FORMAT).put("version", 1).put("kdf", "PBKDF2-HMAC-SHA256").put("iterations", iterations)
            .put("salt", b64.encodeToString(salt)).put("iv", b64.encodeToString(iv)).put("data", b64.encodeToString(data)).toString(2)
    }

    /** The backup's text; [WrongPassword] when the password does not fit or the file was changed. */
    fun open(text: String, password: String): String {
        val j = JSONObject(text.trim())
        require(j.optString("format") == FORMAT) { "format" }
        val iterations = j.getInt("iterations")
        require(iterations in 1..5_000_000) { "iterations" }
        val b64 = Base64.getDecoder()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.DECRYPT_MODE,
            key(password, b64.decode(j.getString("salt")), iterations),
            GCMParameterSpec(128, b64.decode(j.getString("iv")))
        )
        cipher.updateAAD(FORMAT.toByteArray(Charsets.UTF_8))
        return try {
            String(cipher.doFinal(b64.decode(j.getString("data"))), Charsets.UTF_8)
        } catch (_: AEADBadTagException) {
            throw WrongPassword()
        }
    }

    private fun key(password: String, salt: ByteArray, iterations: Int): SecretKeySpec {
        val spec = PBEKeySpec(password.toCharArray(), salt, iterations, 256)
        return SecretKeySpec(SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded, "AES")
    }
}
