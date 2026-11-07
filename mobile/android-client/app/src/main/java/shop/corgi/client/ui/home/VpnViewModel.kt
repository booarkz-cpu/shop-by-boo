package shop.corgi.client.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import shop.corgi.client.vpn.Session

/** The three states of the tunnel the main screen shows. */
enum class VpnStatus { Idle, Connecting, Connected }

/**
 * Everything the main screen draws (v1.5.0, MVVM): the tunnel's state, the session's time and traffic, the ad
 * blocking switch and the streak. Built by [VpnViewModel] only — the screen never reads the service or the store.
 */
data class VpnUiState(
    val status: VpnStatus = VpnStatus.Idle,
    val sessionSeconds: Long = 0L,
    val upSpeed: Long = 0L,
    val downSpeed: Long = 0L,
    val upTotal: Long = 0L,
    val downTotal: Long = 0L,
    val adBlock: Boolean = false,
    /** Ad blocking was switched while connected: it works after the next connection. */
    val adBlockPending: Boolean = false,
    /** Ad blocking needs geosite.dat («Маршруты → Скачать geo-файлы»); the switch did not turn on. */
    val adBlockNeedsGeo: Boolean = false,
    val streakDays: Int = 0,
    val hasProfile: Boolean = false,
    /** v1.6.0 (N10): servers are being removed or a subscription rewritten — the button waits. */
    val configBusy: Boolean = false,
    /** v1.6.0 (N10): the active server was removed — the button waits for another one. */
    val mustChoose: Boolean = false,
    /** v1.6.0 (N10): the address the internet sees and its flag, after connecting. */
    val externalIp: String = "",
    val externalFlag: String = "",
    val error: String = ""
) {
    val isConnected: Boolean get() = status == VpnStatus.Connected

    /** The main button can start the tunnel (it can always stop it). */
    val canConnect: Boolean get() = hasProfile && !configBusy && !mustChoose
}

/** One-off actions the screen carries out for the view model (the VPN permission dialog belongs to the activity). */
sealed interface HomeEvent {
    data object Connect : HomeEvent
}

/** What the view model needs from the tunnel and the settings — the real service in the app, a fake in tests and previews. */
interface VpnEngine {
    /** «off», «connecting» or «on» (ClientVpnService.STATE_*). */
    fun state(): String

    /** Calls [listener] on the main thread on every change of the state; returns the way to stop listening. */
    fun listen(listener: (String) -> Unit): () -> Unit

    fun disconnect()

    fun session(): Session

    fun adBlock(): Boolean

    fun setAdBlock(on: Boolean)

    fun geoReady(): Boolean

    fun streak(): Int

    fun hasProfile(): Boolean

    fun lastError(): String

    /** v1.6.0 (N10): a change of the servers is running ([shop.corgi.client.core.ConfigGate]). */
    fun configBusy(): Boolean = false

    /** v1.6.0 (N10): the active server was removed and no other one is chosen yet. */
    fun mustChoose(): Boolean = false

    /** Calls [listener] when [configBusy] changes; returns the way to stop listening. */
    fun listenConfig(listener: () -> Unit): () -> Unit = {}

    /** v1.6.0 (N10): the external address through the tunnel (blocking; null when unknown). */
    fun externalIp(): shop.corgi.client.core.ExternalIp? = null
}

class VpnViewModel(
    private val engine: VpnEngine,
    private val now: () -> Long = System::currentTimeMillis,
    private val io: kotlinx.coroutines.CoroutineDispatcher = kotlinx.coroutines.Dispatchers.IO
) : ViewModel() {
    private var lookup: Job? = null

    private val mutableState = MutableStateFlow(read(VpnUiState()))
    val state: StateFlow<VpnUiState> = mutableState.asStateFlow()

    private val mutableEvents = MutableSharedFlow<HomeEvent>(extraBufferCapacity = 4)
    val events: SharedFlow<HomeEvent> = mutableEvents.asSharedFlow()

    private var ticker: Job? = null
    private val stopListening = engine.listen { refresh() }
    private val stopConfig = engine.listenConfig { refresh() }

    init {
        refresh()
    }

    /** Reads the tunnel again; while connected, the time and the traffic are read once a second. */
    fun refresh() {
        val next = read(mutableState.value)
        mutableState.value = next
        if (next.isConnected && next.externalIp.isEmpty() && lookup?.isActive != true) {
            lookup = viewModelScope.launch {
                val found = kotlinx.coroutines.withContext(io) { engine.externalIp() }
                if (found != null && mutableState.value.isConnected) {
                    mutableState.update { it.copy(externalIp = found.ip, externalFlag = found.flag) }
                }
            }
        }
        if (next.isConnected && ticker?.isActive != true) {
            ticker = viewModelScope.launch {
                while (isActive && mutableState.value.isConnected) {
                    delay(TICK_MS)
                    mutableState.value = read(mutableState.value)
                }
            }
        }
    }

    /** Idle → asks the screen to connect (the permission dialog, then the service); otherwise disconnects. */
    fun toggleVpn() {
        when (mutableState.value.status) {
            VpnStatus.Idle -> if (read(mutableState.value).canConnect) mutableEvents.tryEmit(HomeEvent.Connect)
            VpnStatus.Connecting, VpnStatus.Connected -> engine.disconnect()
        }
    }

    fun toggleAdBlock() {
        val on = !mutableState.value.adBlock
        if (on && !engine.geoReady()) {
            mutableState.update { it.copy(adBlockNeedsGeo = true) }
            return
        }
        engine.setAdBlock(on)
        mutableState.update {
            it.copy(adBlock = on, adBlockNeedsGeo = false, adBlockPending = it.status != VpnStatus.Idle)
        }
    }

    override fun onCleared() {
        stopListening()
        stopConfig()
    }

    private fun read(previous: VpnUiState): VpnUiState {
        val status = when (engine.state()) {
            STATE_ON -> VpnStatus.Connected
            STATE_CONNECTING -> VpnStatus.Connecting
            else -> VpnStatus.Idle
        }
        val session = if (status == VpnStatus.Connected) engine.session() else Session()
        return previous.copy(
            status = status,
            sessionSeconds = session.seconds(now()),
            upSpeed = session.upSpeed,
            downSpeed = session.downSpeed,
            upTotal = session.upTotal,
            downTotal = session.downTotal,
            adBlock = engine.adBlock(),
            // After a disconnect the next connection takes the switch as it is now.
            adBlockPending = previous.adBlockPending && status != VpnStatus.Idle,
            streakDays = engine.streak(),
            hasProfile = engine.hasProfile(),
            externalIp = if (status == VpnStatus.Connected) previous.externalIp else "",
            externalFlag = if (status == VpnStatus.Connected) previous.externalFlag else "",
            configBusy = engine.configBusy(),
            mustChoose = engine.mustChoose(),
            error = if (status == VpnStatus.Idle) engine.lastError() else ""
        )
    }

    companion object {
        const val TICK_MS = 1000L
        const val STATE_ON = "on"
        const val STATE_CONNECTING = "connecting"
    }
}
