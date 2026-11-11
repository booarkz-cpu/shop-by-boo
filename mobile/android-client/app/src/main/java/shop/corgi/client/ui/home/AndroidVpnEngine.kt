package shop.corgi.client.ui.home

import android.content.Context
import android.os.Handler
import android.os.Looper
import shop.corgi.client.data.Store
import shop.corgi.client.vpn.ClientVpnService
import shop.corgi.client.vpn.Session

/** [VpnEngine] of the app: ClientVpnService, the settings in [Store]. */
class AndroidVpnEngine(context: Context) : VpnEngine {
    private val app = context.applicationContext
    private val store = Store(app)

    override fun state(): String = ClientVpnService.current(app)

    override fun listen(listener: (String) -> Unit): () -> Unit {
        val main = Handler(Looper.getMainLooper())
        val onChange: (String) -> Unit = { value -> main.post { listener(value) } }
        ClientVpnService.listeners.add(onChange)
        return { ClientVpnService.listeners.remove(onChange) }
    }

    override fun disconnect() = ClientVpnService.stop(app)

    override fun session(): Session = ClientVpnService.session

    override fun adBlock(): Boolean = store.settings.adBlock

    override fun setAdBlock(on: Boolean) {
        store.settings = store.settings.copy(adBlock = on)
    }

    override fun geoReady(): Boolean = store.geoReady()


    override fun hasProfile(): Boolean = store.active() != null

    override fun lastError(): String = ClientVpnService.lastError(app)

    override fun externalIp(): shop.corgi.client.core.ExternalIp? = ClientVpnService.ipCheck?.let {
        shop.corgi.client.core.ExternalIp.lookup(it)
    }

    override fun configBusy(): Boolean = shop.corgi.client.core.ConfigGate.busy

    override fun mustChoose(): Boolean = store.mustChoose

    override fun listenConfig(listener: () -> Unit): () -> Unit {
        val main = Handler(Looper.getMainLooper())
        return shop.corgi.client.core.ConfigGate.listen { main.post(listener) }
    }
}
