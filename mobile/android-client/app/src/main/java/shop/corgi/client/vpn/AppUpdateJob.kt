package shop.corgi.client.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import kotlin.concurrent.thread
import shop.corgi.client.R
import shop.corgi.client.core.ApkCheck
import shop.corgi.client.core.tr
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.ui.MainActivity

/**
 * v1.6.1 (N11): «Обновлять автоматически» — once a day the release manifest is checked; a newer client (with a newer
 * Xray core) is downloaded in the background and checked by its SHA-256, then a notification offers to install it
 * (Android asks the user to confirm an app that is not installed by a store). The geo files are refreshed the same day.
 */
class AppUpdateJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        thread {
            val store = Store(this)
            val s = store.settings
            if (s.autoUpdateApp) {
                runCatching { store.checkUpdate() }.getOrNull()?.let { update ->
                    // v1.9.6: on mobile data only a notification; the APK is downloaded after a tap.
                    val metered = getSystemService(android.net.ConnectivityManager::class.java)?.isActiveNetworkMetered ?: true
                    if (store.readyUpdate() == null && !ApkCheck.downloadInBackground(metered)) {
                        // Once per version, not every 6 hours.
                        val prefs = getSharedPreferences("client_update_job", MODE_PRIVATE)
                        if (prefs.getInt("notified", 0) != update.versionCode) {
                            notifyReady(this, update.versionName, downloaded = false)
                            prefs.edit().putInt("notified", update.versionCode).apply()
                        }
                        return@let
                    }
                    runCatching { store.downloadUpdate(update) }.getOrNull()?.let { apk ->
                        // v1.9.2: installed right away when that cannot cut a working VPN; otherwise by a tap.
                        if (ApkCheck.installNow(Build.VERSION.SDK_INT, Xray.running)) {
                            runCatching { ApkInstaller.install(this, apk, background = true, version = update.versionName) }
                                .onFailure { notifyReady(this, update.versionName) }
                        } else {
                            notifyReady(this, update.versionName)
                        }
                    }
                }
            }
            if (s.autoUpdateGeo && store.geoReady() && ApkCheck.due(System.currentTimeMillis(), store.geoUpdatedAt())) {
                runCatching { store.downloadGeo() }
            }
            jobFinished(params, false)
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean = true

    companion object {
        private const val ID = 4202
        private const val CHANNEL = "corgi_client_app_update"
        const val ACTION_INSTALL = "shop.corgi.client.INSTALL_UPDATE"

        fun schedule(context: Context) {
            val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
            val s = Store(context).settings
            if (!s.autoUpdateApp && !s.autoUpdateGeo) {
                scheduler.cancel(ID)
                return
            }
            // v1.9.6: before, the job waited for Wi-Fi once a day; a job scheduled by an older version is replaced.
            val pending = scheduler.getPendingJob(ID)
            if (pending != null && pending.intervalMillis == ApkCheck.JOB_MS && pending.networkType == JobInfo.NETWORK_TYPE_ANY) return
            scheduler.schedule(
                JobInfo.Builder(ID, ComponentName(context, AppUpdateJob::class.java))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPeriodic(ApkCheck.JOB_MS)
                    .setPersisted(true)
                    .build()
            )
        }

        fun notifyReady(context: Context, version: String, downloaded: Boolean = true) {
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            if (Build.VERSION.SDK_INT >= 26 && manager.getNotificationChannel(CHANNEL) == null) {
                manager.createNotificationChannel(
                    NotificationChannel(
                        CHANNEL,
                        tr("Обновление приложения", "App update", "Оновлення застосунку"),
                        NotificationManager.IMPORTANCE_DEFAULT
                    )
                )
            }
            val install =
                PendingIntent.getActivity(
                    context,
                    5,
                    Intent(context, MainActivity::class.java).setAction(ACTION_INSTALL),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
                )
            val builder = if (Build.VERSION.SDK_INT >=
                26
            ) {
                Notification.Builder(context, CHANNEL)
            } else {
                @Suppress("DEPRECATION")
                Notification.Builder(context)
            }
            val title = if (downloaded) {
                tr("Обновление готово", "Update ready", "Оновлення готове")
            } else {
                tr("Доступна версия", "Version available", "Доступна версія")
            }
            val text = if (downloaded) {
                tr("Нажмите, чтобы установить", "Tap to install", "Натисніть, щоб встановити")
            } else {
                tr("Нажмите, чтобы скачать и установить", "Tap to download and install", "Натисніть, щоб завантажити й встановити")
            }
            runCatching {
                manager.notify(
                    9,
                    builder.setSmallIcon(R.drawable.corgi_logo)
                        .setContentTitle("$title — $version")
                        .setContentText(text)
                        .setContentIntent(install).setAutoCancel(true).build()
                )
            }
        }
    }
}
