package shop.corgi.client.core

import java.io.InputStream
import java.io.OutputStream

/**
 * v1.6.0 (N10): the download of geoip.dat and geosite.dat reported as one smooth 0..1 progress. Each file takes its
 * share of the bar by its size (Content-Length; an unknown size counts as an equal share); [report] is called only when
 * the shown percent changes, so the screen is not flooded.
 */
class GeoProgress(private val files: Int, private val report: (Float) -> Unit) {
    private var index = 0
    private var shown = -1

    fun start(file: Int) {
        index = file
        publish(file.toFloat() / files)
    }

    fun copy(input: InputStream, output: OutputStream, total: Long): Long {
        val buffer = ByteArray(BUFFER)
        var done = 0L
        while (true) {
            val n = input.read(buffer)
            if (n < 0) break
            output.write(buffer, 0, n)
            done += n
            val part = if (total > 0) (done.toFloat() / total).coerceAtMost(1f) else 0f
            publish((index + part) / files)
        }
        return done
    }

    fun finish() = publish(1f)

    private fun publish(value: Float) {
        val percent = (value * 100).toInt().coerceIn(0, 100)
        if (percent != shown) {
            shown = percent
            report(percent / 100f)
        }
    }

    companion object {
        const val BUFFER = 64 * 1024
    }
}
