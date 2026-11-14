package shop.remnawave.user.ui

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** v28.131.0: the «Copy MASQUE link» button shows only when the shop hands MASQUE to this customer. */
class MasqueButtonTest {
    private fun data(vararg items: JSONObject) = ShopData(
        dashboard = JSONObject().put("subscription", JSONObject().put("status", "active").put("expires_at", "2099-01-01")),
        masque = JSONObject().put("available", items.isNotEmpty()).put("items", JSONArray(items.toList())),
    )

    private fun item(url: String, over: Boolean = false) = JSONObject().put("subscription_id", 1).put("name", "Lucy").put("url", url).put("over_limit", over)

    private val section = LayoutSection(
        id = "subscription", kind = "subscription", tab = true, title = "", subtitle = "", body = "", icon = "", banner = null,
        buttons = listOf(
            LayoutButton("copy_link", "", "copy_subscription", "", "secondary", "link", "subscribed"),
            LayoutButton("masque", "", "copy_masque", "", "secondary", "link", "subscribed"),
        ),
    )

    @Test
    fun noMasqueNoButton() {
        assertEquals("", data().masqueUrl)
        assertEquals(listOf("copy_link"), visibleButtons(section, data()).map { it.id })
        assertEquals(emptyList<String>(), visibleButtons(section, ShopData()).map { it.id })   // no subscription: neither button
    }

    @Test
    fun aUsableLinkShowsTheButton() {
        val d = data(item("https://shop.example.com/api/masque/sub/1.abc"))
        assertEquals("https://shop.example.com/api/masque/sub/1.abc", d.masqueUrl)
        assertEquals(listOf("copy_link", "masque"), visibleButtons(section, d).map { it.id })
    }

    @Test
    fun aUsedUpLimitOrABadLinkIsSkipped() {
        assertEquals("", data(item("https://x/api/masque/sub/1.a", over = true)).masqueUrl)
        assertEquals("", data(item("http://x/api/masque/sub/1.a")).masqueUrl)
        assertEquals("https://x/2", data(item("https://x/1", over = true), item("https://x/2")).masqueUrl)
    }

    @Test
    fun theActionIsKnown() {
        assertTrue("copy_masque" in KNOWN_ACTIONS)
        assertFalse("copy_masque_v2" in KNOWN_ACTIONS)
    }
}
