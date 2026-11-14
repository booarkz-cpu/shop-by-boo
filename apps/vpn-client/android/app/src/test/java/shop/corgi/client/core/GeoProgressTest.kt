package shop.corgi.client.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GeoProgressTest {
    @Test fun twoFilesMakeOneSmoothBarAndEachPercentIsReportedOnce() {
        val seen = mutableListOf<Float>()
        val progress = GeoProgress(2) { seen += it }
        val first = ByteArray(GeoProgress.BUFFER * 10) { 1 }
        val out = ByteArrayOutputStream()
        progress.start(0)
        assertEquals(first.size.toLong(), progress.copy(ByteArrayInputStream(first), out, first.size.toLong()))
        progress.start(1)
        progress.copy(ByteArrayInputStream(ByteArray(GeoProgress.BUFFER * 4)), ByteArrayOutputStream(), -1L) // size unknown
        progress.finish()
        assertEquals(0f, seen.first())
        assertEquals(1f, seen.last())
        assertTrue("never goes back", seen.zipWithNext().all { (a, b) -> b > a })
        assertTrue("the first file fills half the bar", 0.5f in seen)
        assertEquals("every percent once", seen.size, seen.toSet().size)
        assertEquals(first.size, out.size())
    }
}
