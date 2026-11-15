package shop.corgi.client.core

import java.io.ByteArrayOutputStream
import java.io.InputStream

/**
 * v1.9.8: a subscription is read up to a limit. A server that answers with gigabytes (by mistake or on purpose) used
 * to be read whole into memory and killed the app; now the download stops, the profile keeps its previous servers and
 * shows the reason.
 */
object Capped {
    /** The largest subscription that is read: far above real ones (hundreds of servers are tens of kilobytes). */
    const val SUBSCRIPTION_BYTES = 8 * 1024 * 1024

    class TooLarge(val limit: Int) :
        IllegalStateException(
            tr(
                "Ответ сервера больше ${limit / 1024 / 1024} МБ — это не подписка",
                "The server's answer is over ${limit / 1024 / 1024} MB — not a subscription",
                "Відповідь сервера більша за ${limit / 1024 / 1024} МБ — це не підписка"
            )
        )

    /** Reads the stream as UTF-8 text; stops with [TooLarge] as soon as there is more than [limit] bytes. */
    fun text(input: InputStream, limit: Int = SUBSCRIPTION_BYTES, declared: Long = -1): String {
        if (declared > limit) throw TooLarge(limit)
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(16 * 1024)
        while (true) {
            val n = input.read(buffer)
            if (n < 0) break
            if (out.size() + n > limit) throw TooLarge(limit)
            out.write(buffer, 0, n)
        }
        return out.toString(Charsets.UTF_8.name())
    }
}
