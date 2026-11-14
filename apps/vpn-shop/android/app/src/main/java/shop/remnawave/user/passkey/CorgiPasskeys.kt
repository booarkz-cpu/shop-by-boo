package shop.remnawave.user.passkey

import android.app.Activity
import androidx.credentials.CreatePublicKeyCredentialRequest
import androidx.credentials.CreatePublicKeyCredentialResponse
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetPublicKeyCredentialOption
import androidx.credentials.PublicKeyCredential
import androidx.credentials.exceptions.CreateCredentialCancellationException
import androidx.credentials.exceptions.CreateCredentialException
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.NoCredentialException
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import shop.remnawave.user.ShopApi

/**
 * Passkeys through Android Credential Manager.
 *
 * The shop's cabinet domain is the relying party: it publishes
 * /.well-known/assetlinks.json with this app's signing certificate, so the
 * platform signs ceremonies with the origin `android:apk-key-hash:...` that the
 * server accepts. The challenge binding returned by the server stays in memory
 * for one ceremony and goes back in the X-Shop-Passkey-Binding header.
 * Every call blocks and must run off the main thread (the app's work {} helper).
 */
object CorgiPasskeys {
    class Cancelled : Exception("cancelled")
    class NoPasskey : Exception("no passkey")

    private fun manager(activity: Activity) = CredentialManager.create(activity)

    /** Signs in with a discoverable passkey and returns a bearer token. */
    fun signIn(activity: Activity, base: String, lang: String): String {
        val api = ShopApi(base, "", lang)
        val start = api.post("/api/auth/passkeys/login/options", JSONObject()) as JSONObject
        val option = GetPublicKeyCredentialOption(start.getJSONObject("options").toString())
        val credential = try {
            runBlocking { manager(activity).getCredential(activity, GetCredentialRequest(listOf(option))) }.credential
        } catch (_: GetCredentialCancellationException) {
            throw Cancelled()
        } catch (_: NoCredentialException) {
            throw NoPasskey()
        } catch (exc: GetCredentialException) {
            throw IllegalStateException(exc.errorMessage?.toString() ?: exc.type)
        }
        val json = (credential as? PublicKeyCredential)?.authenticationResponseJson ?: throw IllegalStateException("passkey")
        val result = api.post("/api/auth/passkeys/login/verify",
            JSONObject().put("ticket", start.getString("ticket")).put("credential", JSONObject(json)),
            headers = mapOf("X-Shop-Passkey-Binding" to start.getString("binding"))) as JSONObject
        return result.optString("access_token").ifBlank { throw IllegalStateException("HTTP") }
    }

    /** Creates a passkey for the signed-in account; the account password confirms the owner. */
    fun register(activity: Activity, base: String, token: String, lang: String, password: String, name: String) {
        val api = ShopApi(base, token, lang)
        val body = JSONObject().put("name", name)
        if (password.isNotBlank()) body.put("password", password)
        val start = api.post("/api/auth/passkeys/registration/options", body) as JSONObject
        val request = CreatePublicKeyCredentialRequest(start.getJSONObject("options").toString())
        val created = try {
            runBlocking { manager(activity).createCredential(activity, request) }
        } catch (_: CreateCredentialCancellationException) {
            throw Cancelled()
        } catch (exc: CreateCredentialException) {
            throw IllegalStateException(exc.errorMessage?.toString() ?: exc.type)
        }
        val json = (created as? CreatePublicKeyCredentialResponse)?.registrationResponseJson ?: throw IllegalStateException("passkey")
        api.post("/api/auth/passkeys/registration/verify",
            JSONObject().put("ticket", start.getString("ticket")).put("credential", JSONObject(json)),
            headers = mapOf("X-Shop-Passkey-Binding" to start.getString("binding")))
    }

    fun list(base: String, token: String, lang: String): JSONArray =
        ShopApi(base, token, lang).get("/api/auth/passkeys") as JSONArray

    fun delete(base: String, token: String, lang: String, id: Int, password: String) {
        val body = JSONObject()
        if (password.isNotBlank()) body.put("password", password)
        ShopApi(base, token, lang).post("/api/auth/passkeys/$id/delete", body)
    }
}
