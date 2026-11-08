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
                    runCatching { store.downloadUpdate(update) }.getOrNull()?.let { notifyReady(this, update.versionName) }
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
            if (scheduler.getPendingJob(ID) != null) return
            scheduler.schedule(
                JobInfo.Builder(ID, ComponentName(context, AppUpdateJob::class.java))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
                    .setPeriodic(ApkCheck.DAY_MS)
                    .setPersisted(true)
                    .build()
            )
        }

        fun notifyReady(context: Context, version: String) {
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
            runCatching {
                manager.notify(
                    9,
                    builder.setSmallIcon(R.drawable.corgi_logo)
                        .setContentTitle(tr("Обновление готово", "Update ready", "Оновлення готове") + " — $version")
                        .setContentText(tr("Нажмите, чтобы установить", "Tap to install", "Натисніть, щоб встановити"))
                        .setContentIntent(install).setAutoCancel(true).build()
                )
            }
        }
    }
}
