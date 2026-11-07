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

    override fun streak() = 3

    override fun hasProfile() = true

    override fun lastError() = "boom"
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
        val model = VpnViewModel(engine) { clock }
        assertEquals(VpnStatus.Idle, model.state.value.status)
        assertEquals("boom", model.state.value.error)
        assertEquals(3, model.state.value.streakDays)
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
        val model = VpnViewModel(engine) { clock }
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

    @Test fun textsOfTheScreen() {
        assertEquals("3 days", streakText(3))
        assertEquals("1 day", streakText(1))
        Locale.setDefault(Locale.forLanguageTag("ru"))
        assertEquals("3 дня", streakText(3))
        assertEquals("5 дней", streakText(5))
        assertEquals("21 день", streakText(21))
        assertEquals("12 дней", streakText(12))
        assertEquals("01:02:05", duration(3_725))
        assertEquals(listOf(0, 3, 2, 1, 0), listOf(null, 40, 200, 900, -1).map { signalBars(it) })
    }
}
