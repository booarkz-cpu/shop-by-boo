package shop.corgi.client.core

import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.atomic.AtomicInteger

/**
 * v1.6.0 (N10): while servers or providers are being removed or a subscription is being rewritten, the main button
 * must not start the tunnel on a configuration that is half gone. Every such change runs inside [run]; the main
 * screen listens and keeps its button disabled while [busy] is true.
 */
object ConfigGate {
    private val depth = AtomicInteger(0)
    private val listeners = CopyOnWriteArraySet<() -> Unit>()

    val busy: Boolean get() = depth.get() > 0

    fun <T> run(block: () -> T): T {
        enter()
        try {
            return block()
        } finally {
            leave()
        }
    }

    fun listen(listener: () -> Unit): () -> Unit {
        listeners.add(listener)
        return { listeners.remove(listener) }
    }

    private fun enter() {
        if (depth.getAndIncrement() == 0) announce()
    }

    private fun leave() {
        if (depth.decrementAndGet() == 0) announce()
    }

    private fun announce() = listeners.forEach { it() }
}
