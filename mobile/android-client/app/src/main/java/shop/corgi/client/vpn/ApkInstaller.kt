package shop.corgi.client.vpn

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import java.io.File

/**
 * v1.6.1 (N11): installs the downloaded and checked APK through PackageInstaller (no file is shared with other apps);
 * Android checks that the APK is signed with the same key.
 *
 * v1.9.7: also under a working VPN; [PREFS] remembers to start it again after the update.
 *
 * v1.9.2: without the person. On Android 12 and newer the system installs the update with no confirmation when this app
 * is its own installer of record (it has installed one update of itself before) — permission
 * UPDATE_PACKAGES_WITHOUT_USER_ACTION. Otherwise the system asks; from the background that question cannot be shown,
 * so the «Обновление готово» notification stays and the person installs by a tap.
 */
object ApkInstaller {
    private const val EXTRA_BACKGROUND = "background"
    private const val EXTRA_VERSION = "version"

    const val PREFS = "client_update_install"
    const val KEY_RESUME_VPN = "resume_vpn"

    fun install(context: Context, apk: File, background: Boolean = false, version: String = "", resumeVpn: Boolean = false) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        // v1.9.7: Android 14+ — this app becomes the owner of its updates, so the next ones go without a question even when
        // it was first installed from a browser or a file manager.
        if (Build.VERSION.SDK_INT >= 34) params.setRequestUpdateOwnership(true)
        // The tunnel comes back after the update (BootReceiver, MY_PACKAGE_REPLACED).
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_RESUME_VPN, resumeVpn).commit()
        val id = installer.createSession(params)
        installer.openSession(id).use { session ->
            session.openWrite("corgi-lusi-client.apk", 0, apk.length()).use { out ->
                apk.inputStream().use { it.copyTo(out) }
                session.fsync(out)
            }
            val result =
                PendingIntent.getBroadcast(
                    context,
                    id,
                    Intent(context, InstallResult::class.java).putExtra(EXTRA_BACKGROUND, background).putExtra(EXTRA_VERSION, version),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
                )
            session.commit(result.intentSender)
        }
    }

    /** The system's answer: when it needs the user's confirmation, its own screen is opened. */
    class InstallResult : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -999) == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                if (intent.getBooleanExtra(EXTRA_BACKGROUND, false)) {
                    // Nobody is looking at the app: the system's question cannot be opened from here.
                    AppUpdateJob.notifyReady(context, intent.getStringExtra(EXTRA_VERSION).orEmpty())
                    return
                }
                @Suppress("DEPRECATION")
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
                context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
        }
    }
}
