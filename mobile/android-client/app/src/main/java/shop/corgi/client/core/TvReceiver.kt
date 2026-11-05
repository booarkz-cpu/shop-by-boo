package shop.corgi.client.core

import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.net.URLDecoder
import java.security.SecureRandom

/**
 * «Принять с телефона» on a TV (no camera, no keyboard to speak of): a one-time page in the local network.
 * The TV shows a QR with http://<its address>:<port>/<key>; the phone opens it, pastes a subscription or links and sends
 * the form; the TV adds it. One import, a 128-bit key in the path, 5 minutes, then the server closes.
 */
class TvReceiver(private val onText: (String) -> Unit) {
    val key: String = ByteArray(16).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
    private var server: ServerSocket? = null
    @Volatile var done = false
        private set

    fun start(port: Int = 0): Int {
        val socket = ServerSocket(port, 4)
        socket.soTimeout = 1000
        server = socket
        Thread {
            val deadline = System.currentTimeMillis() + 5 * 60_000
            try {
                while (!done && System.currentTimeMillis() < deadline) {
                    val client = try { socket.accept() } catch (_: SocketTimeoutException) { continue }
                    client.use { handle(it.getInputStream().bufferedReader(), it.getOutputStream()) }
                }
            } catch (_: Exception) { }
            stop()
        }.start()
        return socket.localPort
    }

    fun stop() { done = true; runCatching { server?.close() } }

    private fun handle(input: java.io.BufferedReader, output: java.io.OutputStream) {
        val first = input.readLine() ?: return
        val (method, path) = first.split(" ").let { (it.getOrNull(0) ?: "") to (it.getOrNull(1) ?: "") }
        var length = 0
        while (true) {
            val line = input.readLine() ?: break
            if (line.isEmpty()) break
            if (line.lowercase().startsWith("content-length:")) length = line.substringAfter(":").trim().toIntOrNull() ?: 0
        }
        if (path.substringBefore("?") != "/$key") return reply(output, 404, "Not found")
        if (method == "GET") return reply(output, 200, PAGE)
        if (method != "POST" || length !in 1..200_000) return reply(output, 400, "Bad request")
        val body = CharArray(length).also { var read = 0; while (read < length) { val n = input.read(it, read, length - read); if (n < 0) break; read += n } }
        val text = URLDecoder.decode(String(body).substringAfter("text=", ""), "UTF-8").trim()
        if (text.isEmpty()) return reply(output, 400, PAGE)
        onText(text)
        done = true
        reply(output, 200, DONE)
    }

    private fun reply(output: java.io.OutputStream, code: Int, html: String) {
        val bytes = html.toByteArray()
        output.write(("HTTP/1.0 $code OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: ${bytes.size}\r\n" +
            "Cache-Control: no-store\r\nConnection: close\r\n\r\n").toByteArray())
        output.write(bytes); output.flush()
    }

    companion object {
        private const val STYLE = "<meta name=viewport content='width=device-width'><style>body{font-family:sans-serif;background:#0e1116;color:#f1f5f9;padding:20px}" +
            "textarea{width:100%;height:160px}button{margin-top:12px;padding:12px 20px;background:#f2994a;border:0;border-radius:8px;font-size:16px}</style>"
        val PAGE: String get() = "<!doctype html>$STYLE<h2>" + tr("Корги Люси: клиент", "Corgi Lusi: client", "Коргі Люсі: клієнт") + "</h2><p>" +
            tr("Вставьте ссылку на подписку или ссылки на серверы — они появятся на телевизоре.",
                "Paste a subscription URL or server links — they will appear on the TV.",
                "Вставте посилання на підписку або посилання на сервери — вони з'являться на телевізорі.") +
            "</p><form method=post><textarea name=text autofocus></textarea><br><button>" + tr("Отправить на ТВ", "Send to the TV", "Надіслати на ТБ") + "</button></form>"
        val DONE: String get() = "<!doctype html>$STYLE<h2>" + tr("Готово", "Done", "Готово") + "</h2><p>" +
            tr("Подписка отправлена на телевизор.", "The subscription was sent to the TV.", "Підписку надіслано на телевізор.") + "</p>"

        /** The device's address in the local network (IPv4, not loopback). */
        fun localAddress(): String? = NetworkInterface.getNetworkInterfaces().toList().filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }.firstOrNull { it is java.net.Inet4Address && it.isSiteLocalAddress }?.hostAddress
    }
}
