package shop.corgi.client.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import java.util.zip.ZipInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** v1.10.1: the log archive carries no keys, server links or addresses (REQ-CLIENT-0026). */
class RedactTest {
    private val key = "b831381d-6324-4d53-ad4f-8cda48b30811"
    private val m = Redact.MASK

    @Test fun theCoreLogKeepsItsShapeButNotTheServersAndSites() {
        assertEquals(
            "2026/11/15 10:00:01.123 [Info] [123] proxy/vless/outbound: tunneling request to tcp:$m:443 via $m:443",
            Redact.line(
                "2026/11/15 10:00:01.123 [Info] [123] proxy/vless/outbound: tunneling request to tcp:www.youtube.com:443 via 203.0.113.9:443"
            )
        )
        assertEquals(
            "2026/11/15 10:00:01 from 127.0.0.1:50123 accepted tcp:$m:443 [proxy]",
            Redact.line("2026/11/15 10:00:01 from 127.0.0.1:50123 accepted tcp:142.250.74.46:443 [proxy]")
        )
    }

    @Test fun linksAndKeysOfTheSubscriptionAreMasked() {
        assertEquals(
            "import vless://$m done",
            Redact.line("import vless://$key@de1.example.net:443?security=reality&pbk=AbC#Германия done")
        )
        for (scheme in listOf("vmess", "trojan", "ss", "hysteria2", "hy2", "tuic", "masque")) {
            assertEquals("$scheme://$m", Redact.line("$scheme://secret@host.example:443"))
        }
        assertEquals("user b831$m connected", Redact.line("user $key connected"))
        assertEquals(
            "subscription https://$m/$m answered 200",
            Redact.line("subscription https://sub.example.net/api/sub/AbCdEf123?x=1 answered 200")
        )
        assertEquals("""{"id":"b831$m","password":"$m","port":443}""", Redact.line("""{"id":"$key","password":"hunter2","port":443}"""))
        assertEquals("socks pass=$m user=ip12345 pid=4321 key: $m", Redact.line("socks pass=Zk3jd9 user=ip12345 pid=4321 key: s3cr3t"))
    }

    @Test fun localAddressesTimesAndVersionsStay() {
        val line = "Corgi Lusi client 1.10.1 (1101) Android 14 error: timeout after 15000 ms at 12:34:56"
        assertEquals(line, Redact.line(line))
        assertEquals(
            "dns udp:$m:53 and $m and ::1 and 192.168.1.10 and 10.0.0.1",
            Redact.line("dns udp:[2001:db8::1]:53 and 2a00:1450:4001:82b::200e and ::1 and 192.168.1.10 and 10.0.0.1")
        )
        assertEquals(
            "ping http://10.0.2.2:8080/$m and https://$m/$m",
            Redact.line("ping http://10.0.2.2:8080/health and https://www.gstatic.com/generate_204")
        )
        assertTrue(Redact.local("127.0.0.1") && Redact.local("172.20.1.1") && Redact.local("198.18.0.1"))
        assertFalse(Redact.local("8.8.8.8") || Redact.local("172.32.0.1") || Redact.local("300.1.1.1") || Redact.local("host"))
    }

    @Test fun theArchiveIsMaskedLineByLine() {
        val dir = Files.createTempDirectory("logs").toFile()
        File(dir, "xray.log").writeText("accepted tcp:example.org:443\nuuid $key\n")
        val out = ByteArrayOutputStream()
        LogZip.write(dir.listFiles()!!.toList(), "about", out)
        var log = ""
        ZipInputStream(ByteArrayInputStream(out.toByteArray())).use { zip ->
            while (true) {
                val e = zip.nextEntry ?: break
                if (e.name == "logs/xray.log") log = zip.readBytes().decodeToString()
            }
        }
        assertEquals("accepted tcp:$m:443\nuuid b831$m\n", log)
        assertFalse(log.contains("example.org") || log.contains(key))
    }
}
