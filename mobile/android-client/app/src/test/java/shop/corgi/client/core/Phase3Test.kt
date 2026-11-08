package shop.corgi.client.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import java.util.zip.ZipInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import shop.corgi.client.core.Automation.Step

/** v1.8.0 (N12, phase 3): logs in a .zip and Intents for automation apps. */
class Phase3Test {
    @Test fun logsGoIntoOneArchiveWithANote() {
        val dir = Files.createTempDirectory("logs").toFile()
        File(dir, "app.log").writeText("app line\n")
        File(dir, "xray.log").writeText("x".repeat(10))
        File(dir, "notes.txt").writeText("not a log")
        val out = ByteArrayOutputStream()
        LogZip.write(dir.listFiles()!!.toList(), "Corgi Lusi 1.8.0", out)
        val names = mutableMapOf<String, String>()
        ZipInputStream(ByteArrayInputStream(out.toByteArray())).use { zip ->
            while (true) {
                val e = zip.nextEntry ?: break
                names[e.name] = zip.readBytes().decodeToString()
            }
        }
        assertEquals(setOf("about.txt", "logs/app.log", "logs/xray.log"), names.keys)
        assertEquals("Corgi Lusi 1.8.0", names["about.txt"])
        assertEquals("app line\n", names["logs/app.log"])
        assertTrue(LogZip.name(0).matches(Regex("corgi-lusi-logs-\\d{4}-\\d{2}-\\d{2}-\\d{4}\\.zip")))
    }

    @Test fun automationOnlyWhenAllowed() {
        assertEquals(Step.NOTHING, Automation.decide(Automation.CONNECT, allowed = false, running = false))
        assertEquals(Step.START, Automation.decide(Automation.CONNECT, allowed = true, running = false))
        assertEquals(Step.NOTHING, Automation.decide(Automation.CONNECT, allowed = true, running = true))
        assertEquals(Step.STOP, Automation.decide(Automation.DISCONNECT, allowed = true, running = true))
        assertEquals(Step.START, Automation.decide(Automation.TOGGLE, allowed = true, running = false))
        assertEquals(Step.STOP, Automation.decide(Automation.TOGGLE, allowed = true, running = true))
        assertEquals(Step.NOTHING, Automation.decide("other.ACTION", allowed = true, running = false))
    }

    @Test fun theServerExtraMustBeInTheList() {
        assertEquals("2", Automation.server(2, 3))
        assertNull(Automation.server(3, 3))
        assertNull(Automation.server(-1, 3))
        assertNull(Automation.server(null, 3))
    }

    @Test fun settingsKeepTheSwitch() {
        assertEquals(Settings(allowAutomation = true), Settings.of(Settings(allowAutomation = true).toJson()))
    }
}
