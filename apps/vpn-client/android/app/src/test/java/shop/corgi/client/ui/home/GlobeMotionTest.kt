package shop.corgi.client.ui.home

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** v1.9.3: the meridians of the turning globe stay on the globe and move in one direction. */
class GlobeMotionTest {
    @Test
    fun meridiansStayInsideTheGlobe() {
        for (step in 0..100) {
            val lines = GlobeMotion.meridians(step / 100f)
            assertEquals(GlobeMotion.MERIDIANS, lines.size)
            assertTrue(lines.all { it >= -1f && it <= 1f })
        }
    }

    @Test
    fun aMeridianMovesFromLeftToRight() {
        val first = (0..24).map { GlobeMotion.meridians(it / 100f)[0] }
        assertEquals(-1f, first.first(), 0.001f)
        assertTrue("moves to the right all the way", first.zipWithNext().all { (a, b) -> b > a })
    }

    @Test
    fun aFullTurnBringsTheSamePicture() {
        val start = GlobeMotion.meridians(0f).sorted()
        val end = GlobeMotion.meridians(1f).sorted()
        start.zip(end).forEach { (a, b) -> assertEquals(a, b, 0.001f) }
        // A quarter of a turn moves every meridian to the place of the next one.
        val quarter = GlobeMotion.meridians(0.25f).sorted()
        start.zip(quarter).forEach { (a, b) -> assertEquals(a, b, 0.001f) }
    }
}
