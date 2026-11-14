package shop.corgi.client.core

import java.io.File
import java.io.OutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * v1.8.0 (N12, phase 3): «Экспорт логов» — the app's and the core's logs (and the network log) in one .zip for the
 * support, with a short note about the app and the device. The user picks where to save it; nothing is sent by itself.
 */
object LogZip {
    /** Every log file at most [MAX_FILE] bytes from its end, so a huge log does not make a huge archive. */
    const val MAX_FILE = 2_000_000L

    fun write(files: List<File>, about: String, out: OutputStream) {
        ZipOutputStream(out).use { zip ->
            zip.putNextEntry(ZipEntry("about.txt"))
            zip.write(about.toByteArray())
            zip.closeEntry()
            files.filter { it.isFile && it.name.endsWith(".log") }.distinctBy { it.name }.forEach { file ->
                zip.putNextEntry(ZipEntry("logs/" + file.name))
                file.inputStream().use { input ->
                    val skip = (file.length() - MAX_FILE).coerceAtLeast(0)
                    if (skip > 0) input.skip(skip)
                    input.copyTo(zip)
                }
                zip.closeEntry()
            }
        }
    }

    /** «corgi-lusi-logs-2026-11-08-1205.zip» — the name offered in the save dialog. */
    fun name(millis: Long): String =
        "corgi-lusi-logs-" + java.text.SimpleDateFormat("yyyy-MM-dd-HHmm", java.util.Locale.ROOT).format(java.util.Date(millis)) + ".zip"
}
