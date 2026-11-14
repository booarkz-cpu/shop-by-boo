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
import shop.corgi.client.R
import shop.corgi.client.core.tr
import shop.corgi.client.data.Store
import shop.corgi.client.ui.MainActivity
import kotlin.concurrent.thread

/**
 * «Провайдеры → Автообновление»: subscriptions are updated in the background by the system's job scheduler at the
 * chosen interval (with the network on); «Уведомлять об обновлениях» posts what changed.
 */
class UpdateJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        thread {
            val store = Store(this)
            val before = store.profiles.associate { it.id to it.servers().size }
            val updated = runCatching { store.updateDue() }.getOrDefault(emptyList())
            if (store.settings.notifyUpdates && updated.isNotEmpty()) notify(this, updated.joinToString(", ") { p ->
                val was = before[p.id] ?: 0
                val now = p.servers().size
                "${p.title}: " + if (p.error.isNotBlank()) p.error else "$now" + (if (now != was) " (${if (now > was) "+" else ""}${now - was})" else "")
            })
            jobFinished(params, false)
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean = true

    companion object {
        private const val ID = 4201
        private const val CHANNEL = "corgi_client_updates"

        /** Called on start and when the provider settings change: on with the interval, or cancelled. */
        fun schedule(context: Context) {
            val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
            val s = Store(context).settings
            if (!s.autoUpdate) { scheduler.cancel(ID); return }
            val period = maxOf(s.updateMinutes, 15) * 60_000L
            val current = scheduler.getPendingJob(ID)
            if (current != null && current.intervalMillis == period) return
            scheduler.schedule(JobInfo.Builder(ID, ComponentName(context, UpdateJob::class.java))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPeriodic(period).setPersisted(true).build())
        }

        private fun notify(context: Context, text: String) {
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            if (Build.VERSION.SDK_INT >= 26 && manager.getNotificationChannel(CHANNEL) == null)
                manager.createNotificationChannel(NotificationChannel(CHANNEL, tr("Обновления подписок", "Subscription updates", "Оновлення підписок"), NotificationManager.IMPORTANCE_LOW))
            val open = PendingIntent.getActivity(context, 3, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(context, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(context)
            runCatching {
                manager.notify(8, builder.setSmallIcon(R.drawable.corgi_logo).setContentTitle(tr("Подписки обновлены", "Subscriptions updated", "Підписки оновлено"))
                    .setContentText(text).setStyle(Notification.BigTextStyle().bigText(text)).setContentIntent(open).setAutoCancel(true).build())
            }
        }
    }
}
