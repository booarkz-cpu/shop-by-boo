package shop.remnawave.admin.update

import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import shop.remnawave.admin.BuildConfig
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlin.concurrent.thread

/**
 * v3.7.0: the update without the person. Once a day a background job finds the newer version in the shop's release on
 * GitHub, downloads the APK, checks its SHA-256 and hands it to the system installer.
 *
 * Android 12 and newer install it with no confirmation when this app is its own installer of record (it has installed
 * one update of itself before) — permission UPDATE_PACKAGES_WITHOUT_USER_ACTION. Otherwise the system has to ask, and
 * from the background that question cannot be shown: the update is installed at the next start of the app.
 * v28.137.0: every 6 hours, also under a working VPN (an update restarts the app; the VPN is started again after it).
 */
object AppUpdater {
    private const val JOB = 4301
    const val STEM = "corgi-lusi-android-admin"
    private const val EXTRA_BACKGROUND = "background"

    fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) { val n = input.read(buffer); if (n < 0) break; digest.update(buffer, 0, n) }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    fun matches(file: File, expected: String): Boolean = file.isFile && file.length() > 0 && sha256(file) == expected.lowercase()

    /**
     * Whether the background job installs by itself: wherever the system can do it silently (Android 12+). v28.137.0: a
     * working VPN no longer holds the update back — the app restarts it after the update ([ResumeAfterUpdate]).
     */
    fun installNow(sdk: Int): Boolean = sdk >= 31

    const val PREFS = "app_update_install"
    const val KEY_RESUME_VPN = "resume_vpn"

    /** The admin app has no VPN of its own. */
    fun vpnRunning(@Suppress("UNUSED_PARAMETER") context: Context): Boolean = false

    /** The APK of [update] in the app's cache, checked by its SHA-256 (call off the main thread). */
    fun download(context: Context, update: AppUpdate): File {
        require(update.apk.startsWith(AppUpdate.RELEASES) && update.apk.endsWith("/$STEM.apk")) { "apk url" }
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        val apk = File(dir, "$STEM-${update.versionCode}.apk")
        if (matches(apk, update.sha256)) return apk
        dir.listFiles()?.forEach { it.delete() }
        val tmp = File(dir, "download.part")
        val connection = (URL(update.apk).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15000; readTimeout = 30000; instanceFollowRedirects = true
        }
        try {
            require(connection.responseCode == 200) { "http" }
            connection.inputStream.use { input -> tmp.outputStream().use { input.copyTo(it) } }
        } finally {
            connection.disconnect()
        }
        if (!matches(tmp, update.sha256)) { tmp.delete(); error("checksum") }
        require(tmp.renameTo(apk)) { "rename" }
        return apk
    }

    /** Hands the checked APK to the system installer; Android checks that it is signed with the same key. */
    fun install(context: Context, apk: File, background: Boolean, resumeVpn: Boolean = false) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        // v28.137.0: Android 14+ — the app becomes the owner of its updates, the next ones go without a question.
        if (Build.VERSION.SDK_INT >= 34) params.setRequestUpdateOwnership(true)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_RESUME_VPN, resumeVpn).commit()
        val id = installer.createSession(params)
        installer.openSession(id).use { session ->
            session.openWrite("$STEM.apk", 0, apk.length()).use { out ->
                apk.inputStream().use { it.copyTo(out) }
                session.fsync(out)
            }
            val result = PendingIntent.getBroadcast(context, id, Intent(context, InstallResult::class.java).putExtra(EXTRA_BACKGROUND, background),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            session.commit(result.intentSender)
        }
    }

    /** The job every 6 hours (was daily); scheduled again at every start and after an update; an older daily job is replaced. */
    fun schedule(context: Context) {
        val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
        if (scheduler.getPendingJob(JOB)?.intervalMillis == AppUpdate.JOB) return
        scheduler.schedule(JobInfo.Builder(JOB, ComponentName(context, AppUpdateJob::class.java))
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPeriodic(AppUpdate.JOB).build())
    }

    /** The system's answer: when it needs a confirmation and the person is in the app, its own screen is opened. */
    class InstallResult : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -999) != PackageInstaller.STATUS_PENDING_USER_ACTION) return
            if (intent.getBooleanExtra(EXTRA_BACKGROUND, false)) return   // the window at the next start offers it
            @Suppress("DEPRECATION")
            val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
            runCatching { context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        }
    }
}

class AppUpdateJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        thread {
            runCatching {
                if (!BuildConfig.DEBUG && !AppUpdate.fromStore(AppUpdate.installer(this))) {
                    AppUpdate.latest(BuildConfig.VERSION_CODE)?.let { update ->
                        val apk = AppUpdater.download(this, update)
                        if (AppUpdater.installNow(Build.VERSION.SDK_INT)) AppUpdater.install(this, apk, background = true, resumeVpn = AppUpdater.vpnRunning(this))
                    }
                }
            }
            jobFinished(params, false)
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean = true
}

/** v28.137.0: the update job is scheduled again right after an update (the admin app has no VPN to bring back). */
class ResumeAfterUpdate : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) AppUpdater.schedule(context)
    }
}
