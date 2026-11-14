package shop.corgi.client.core

import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * «Журналы туннеля»: Xray writes its log (level from the settings) to logs/xray.log; the app adds its own lines
 * (connect, disconnect, errors, pings) to logs/app.log. On every connection the files rotate (xray_1.log …, up to
 * [KEEP]); files older than the chosen hours are deleted. Nothing leaves the device unless the user exports it.
 */
class Logs(filesDir: File) {
    val dir = File(filesDir, "logs").apply { mkdirs() }
    val xray: File get() = File(dir, "xray.log")
    /** v1.7.4 (N12): «Журнал сети» — Xray's access log of this connection (started afresh on every connection). */
    val access: File get() = File(dir, "access.log")
    private val app: File get() = File(dir, "app.log")

    fun files(): List<File> = dir.listFiles { f -> f.isFile && f.name.endsWith(".log") }?.sortedByDescending { it.lastModified() } ?: emptyList()

    /** Before a connection: the previous xray.log becomes xray_1.log (and so on); old files go. */
    fun rotate(hours: Int, now: Long = System.currentTimeMillis()) {
        access.delete()
        if (hours > 0) files().filter { now - it.lastModified() > hours * 3_600_000L }.forEach { it.delete() }
        if (xray.length() == 0L) return
        File(dir, "xray_$KEEP.log").delete()
        for (i in KEEP - 1 downTo 1) File(dir, "xray_$i.log").takeIf { it.exists() }?.renameTo(File(dir, "xray_${i + 1}.log"))
        xray.renameTo(File(dir, "xray_1.log"))
    }

    fun app(line: String, now: Long = System.currentTimeMillis()) {
        runCatching {
            if (app.length() > 512 * 1024) app.renameTo(File(dir, "app_1.log"))
            app.appendText("${SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.ROOT).format(Date(now))} $line\n")
        }
    }

    /** The last ``limit`` lines of a file that contain ``query`` (case-insensitive). */
    fun lines(file: File, query: String = "", limit: Int = 500): List<String> {
        if (!file.exists()) return emptyList()
        val q = query.trim().lowercase()
        return file.readLines().filter { q.isEmpty() || it.lowercase().contains(q) }.takeLast(limit)
    }

    fun clear() { files().forEach { it.delete() } }

    companion object {
        const val KEEP = 4

        /** «Все» / Error / Warning / Info: Xray marks lines «[Error]», «[Warning]» …; the app's own errors say «error». */
        fun matches(line: String, level: String): Boolean = when (level) {
            "error" -> line.contains("[Error]", true) || line.contains("] error", true) || line.contains("failed", true)
            "warning" -> line.contains("[Warning]", true)
            "info" -> line.contains("[Info]", true) || line.contains("[VPN]")
            else -> true
        }
    }
}
