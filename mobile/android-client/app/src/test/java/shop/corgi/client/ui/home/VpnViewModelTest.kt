package shop.corgi.client.ui.home

import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import shop.corgi.client.vpn.Session

/** The engine of the tests: the state, the session and the settings in fields; disconnect switches it off. */
private class FakeEngine : VpnEngine {
    var state = "off"
    var session = Session()
    var adBlockOn = false
    var geo = true
    var disconnects = 0
    val listeners = mutableListOf<(String) -> Unit>()

    fun set(value: String) {
        state = value
        listeners.toList().forEach { it(value) }
    }

    override fun state() = state

    override fun listen(listener: (String) -> Unit): () -> Unit {
        listeners += listener
        return { listeners -= listener }
    }

    override fun disconnect() {
        disconnects++
        set("off")
    }

    override fun session() = session

    override fun adBlock() = adBlockOn

    override fun setAdBlock(on: Boolean) {
        adBlockOn = on
    }

    override fun geoReady() = geo


    override fun hasProfile() = true

    override fun lastError() = "boom"

    var busy = false
    var choose = false
    val configListeners = mutableListOf<() -> Unit>()

    fun config(busy: Boolean = this.busy, choose: Boolean = this.choose) {
        this.busy = busy
        this.choose = choose
        configListeners.toList().forEach { it() }
    }

    override fun configBusy() = busy

    override fun mustChoose() = choose

    var ip: shop.corgi.client.core.ExternalIp? = null
    var lookups = 0

    override fun externalIp(): shop.corgi.client.core.ExternalIp? {
        lookups++
        return ip
    }

    override fun listenConfig(listener: () -> Unit): () -> Unit {
        configListeners += listener
        return { configListeners -= listener }
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class VpnViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private var clock = 0L

    @Before fun setUp() {
        Dispatchers.setMain(dispatcher)
        Locale.setDefault(Locale.ENGLISH)
    }

    @After fun tearDown() = Dispatchers.resetMain()

    @Test fun idleAsksTheScreenToConnectAndFollowsTheService() = runTest(dispatcher) {
        val engine = FakeEngine()
        val model = VpnViewModel(engine, { clock }, dispatcher)
        assertEquals(VpnStatus.Idle, model.state.value.status)
        assertEquals("boom", model.state.value.error)
        val event = async { model.events.first() }
        runCurrent()
        model.toggleVpn()
        assertEquals(HomeEvent.Connect, event.await())
        engine.set("connecting")
        assertEquals(VpnStatus.Connecting, model.state.value.status)
        assertEquals("", model.state.value.error)
        engine.session = Session(startedAt = 1_000)
        engine.set("on")
        assertTrue(model.state.value.isConnected)
        // Once a second the time and the traffic are read again.
        engine.session = engine.session.add(10, 500)
        clock = 4_000
        advanceTimeBy(VpnViewModel.TICK_MS + 1)
        assertEquals(3L, model.state.value.sessionSeconds)
        assertEquals(500L, model.state.value.downSpeed)
        assertEquals(10L, model.state.value.upTotal)
        model.toggleVpn()
        assertEquals(1, engine.disconnects)
        assertEquals(VpnStatus.Idle, model.state.value.status)
        assertEquals(0L, model.state.value.sessionSeconds)
        advanceTimeBy(5 * VpnViewModel.TICK_MS)
    }

    @Test fun adBlockNeedsGeoFilesAndAppliesOnTheNextConnection() = runTest(dispatcher) {
        val engine = FakeEngine().apply { geo = false }
        val model = VpnViewModel(engine, { clock }, dispatcher)
        model.toggleAdBlock()
        assertFalse(model.state.value.adBlock)
        assertTrue(model.state.value.adBlockNeedsGeo)
        assertFalse(engine.adBlockOn)
        engine.geo = true
        model.toggleAdBlock()
        assertTrue(model.state.value.adBlock && engine.adBlockOn)
        assertFalse(model.state.value.adBlockNeedsGeo || model.state.value.adBlockPending)
        engine.set("on")
        model.toggleAdBlock()
        assertTrue(model.state.value.adBlockPending)
        assertFalse(engine.adBlockOn)
        engine.set("off")
        assertFalse("the next connection takes the switch as it is", model.state.value.adBlockPending)
        advanceTimeBy(3 * VpnViewModel.TICK_MS)
    }

    @Test fun theButtonWaitsWhileServersChangeAndAfterTheActiveOneIsRemoved() = runTest(dispatcher) {
        val engine = FakeEngine()
        val model = VpnViewModel(engine, { clock }, dispatcher)
        val events = mutableListOf<HomeEvent>()
        val collecting = async { model.events.collect { events += it } }
        runCurrent()
        engine.config(busy = true)
        assertTrue(model.state.value.configBusy)
        assertFalse(model.state.value.canConnect)
        assertFalse(buttonEnabled(model.state.value))
        model.toggleVpn()
        runCurrent()
        assertTrue("no connection on a configuration being changed", events.isEmpty())
        engine.config(busy = false, choose = true)
        assertFalse("the removed server is not replaced silently", buttonEnabled(model.state.value))
        model.toggleVpn()
        runCurrent()
        assertTrue(events.isEmpty())
        engine.config(choose = false)
        assertTrue(buttonEnabled(model.state.value))
        model.toggleVpn()
        runCurrent()
        assertEquals(listOf<HomeEvent>(HomeEvent.Connect), events)
        engine.set("on")
        engine.config(busy = true)
        assertFalse("stopping waits for the change too", buttonEnabled(model.state.value))
        engine.config(busy = false)
        assertTrue(buttonEnabled(model.state.value))
        // Disconnected, so the once-a-second ticker ends and the test scheduler becomes idle.
        engine.set("off")
        collecting.cancel()
        advanceTimeBy(VpnViewModel.TICK_MS)
    }

    @Test fun theExternalAddressAfterConnectingAndGoneAfterDisconnecting() = runTest(dispatcher) {
        val engine = FakeEngine()
        engine.ip = shop.corgi.client.core.ExternalIp("203.0.113.7", "FI")
        val model = VpnViewModel(engine, { clock }, dispatcher)
        engine.set("on")
        runCurrent()
        assertEquals("203.0.113.7", model.state.value.externalIp)
        assertEquals("\uD83C\uDDEB\uD83C\uDDEE", model.state.value.externalFlag)
        advanceTimeBy(3 * VpnViewModel.TICK_MS)
        assertEquals("looked up once per connection", 1, engine.lookups)
        engine.set("off")
        assertEquals("", model.state.value.externalIp)
        advanceTimeBy(VpnViewModel.TICK_MS)
    }

    @Test fun textsOfTheScreen() {
        assertEquals("01:02:05", duration(3_725))
        assertEquals(listOf(0, 3, 2, 2, 1, 0), listOf(null, 40, 100, 300, 301, -1).map { signalBars(it) })
    }
}
