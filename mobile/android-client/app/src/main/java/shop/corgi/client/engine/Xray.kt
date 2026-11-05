package shop.corgi.client.engine

import android.content.Context
import java.lang.reflect.Proxy

/**
 * Xray-core through libv2ray.aar (AndroidLibXrayLite, LGPL-3.0; scripts/mobile/build-xray-aar.sh) — the same engine as
 * the customer app. Reached by reflection, so the app also compiles without the library (it then says so).
 */
object Xray {
    private var controller: Any? = null

    fun available(): Boolean = try { Class.forName("libv2ray.Libv2ray"); true } catch (_: Throwable) { false }

    fun version(): String = try {
        Class.forName("libv2ray.Libv2ray").getMethod("checkVersionX").invoke(null) as String
    } catch (_: Throwable) { "" }

    /** Starts the core on the tunnel's file descriptor; geo files (if any) are read from filesDir. */
    fun start(context: Context, config: String, tunFd: Int, onStop: () -> Unit) {
        val lib = Class.forName("libv2ray.Libv2ray")
        lib.getMethod("initCoreEnv", String::class.java, String::class.java).invoke(null, context.filesDir.absolutePath, "")
        val handlerType = Class.forName("libv2ray.CoreCallbackHandler")
        // gomobile maps Go int to Java long: every callback returns a long.
        val handler = Proxy.newProxyInstance(handlerType.classLoader, arrayOf(handlerType)) { _, method, _ ->
            if (method.name == "shutdown") onStop()
            when (method.returnType) { java.lang.Long.TYPE -> 0L; Integer.TYPE -> 0; else -> null }
        }
        val core = lib.getMethod("newCoreController", handlerType).invoke(null, handler)!!
        core.javaClass.getMethod("startLoop", String::class.java, Integer.TYPE).invoke(core, config, tunFd)
        controller = core
    }

    /**
     * Real delay through a server: a separate Xray instance with only that outbound requests ``url`` (libv2ray
     * measureOutboundDelay). Milliseconds, or -1 when the server did not answer.
     */
    fun measure(context: Context, config: String, url: String): Long = try {
        val lib = Class.forName("libv2ray.Libv2ray")
        lib.getMethod("initCoreEnv", String::class.java, String::class.java).invoke(null, context.filesDir.absolutePath, "")
        (lib.getMethod("measureOutboundDelay", String::class.java, String::class.java).invoke(null, config, url) as Long).takeIf { it > 0 } ?: -1
    } catch (_: Throwable) { -1 }

    /** Bytes through ``tag`` since the last call ("uplink" / "downlink"); needs «stats» in the config. 0 when unknown. */
    fun traffic(tag: String, direction: String): Long = try {
        val core = controller ?: return 0
        core.javaClass.getMethod("queryStats", String::class.java, String::class.java).invoke(core, tag, direction) as Long
    } catch (_: Throwable) { 0 }

    fun stop() {
        val core = controller ?: return
        controller = null
        try { core.javaClass.getMethod("stopLoop").invoke(core) } catch (_: Throwable) { }
    }

    val running: Boolean get() = controller != null
}
