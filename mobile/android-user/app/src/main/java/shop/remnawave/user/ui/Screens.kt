package shop.remnawave.user.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.HeadsetMic
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.RadioButtonUnchecked
import androidx.compose.material.icons.rounded.RocketLaunch
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONArray
import org.json.JSONObject

/** Buttons of a section visible to this customer (audience «с подпиской» / «без подписки»). */
private val ENGINE_ACTIONS = setOf("vpn_mode", "vpn_server", "split_tunnel")

fun visibleButtons(section: LayoutSection, data: ShopData): List<LayoutButton> = section.buttons.filter {
    // Buttons of the embedded VPN exist only in builds that carry the engine (libv2ray.aar).
    if (it.action in ENGINE_ACTIONS && !shop.remnawave.user.vpn.XrayEngine.available()) return@filter false
    when (it.audience) {
        "subscribed" -> data.subscribed
        "unsubscribed" -> !data.subscribed
        else -> true
    }
}

@Composable
fun SectionScreen(layout: AppLayout, section: LayoutSection, base: String, data: ShopData, ui: UiFlags, actions: ShopActions) {
    val theme = layout.theme
    Column(
        Modifier.fillMaxSize().background(theme.background).statusBarsPadding().verticalScroll(rememberScrollState())
            .padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        if (section.kind == "vpn") {
            VpnScreen(layout, section, base, data, ui, actions)
        } else {
            SectionTitle(section.title, theme)
            if (ui.offline) Muted(layout.text("offline"), theme, center = true)
            if (ui.notice.isNotBlank()) NoticeLine(ui.notice, theme)
            SectionBanner(base, section.banner, theme) { actions.link(it) }
            Muted(section.subtitle, theme)
            when (section.kind) {
                "locations" -> LocationsBody(layout, data)
                "premium" -> PremiumBody(layout, data, ui, actions)
                "subscription" -> { SubscriptionBody(layout, data, actions); InsightsCards(layout, data, actions) }
                "devices" -> DevicesBody(layout, data, actions)
                "family" -> FamilyBody(layout, data, actions)
                "referral" -> ReferralBody(layout, data)
                "wallet" -> WalletBody(layout, data, ui, actions)
                "notifications" -> NotificationsBody(layout, data, actions)
                "status" -> StatusBody(layout, data)
                "security" -> SecurityBody(layout, data, actions)
                "info" -> InfoBody(layout, base, data, actions)
                "giveaways" -> GiveawaysBody(layout, data, ui, actions)
                else -> {}
            }
            if (section.body.isNotBlank()) Card(theme) { Text(section.body, color = theme.text, fontSize = 15.sp, lineHeight = 22.sp) }
            val buttons = visibleButtons(section, data)
            if (section.kind == "settings" || section.kind == "support") {
                ButtonRows(layout, buttons, ui, actions)
            } else {
                buttons.forEach { b -> ActionButton(b, theme, enabled = !ui.busy) { actions.run(b) } }
            }
            if (section.kind == "settings" && layout.feature("settings_version") && ui.version.isNotBlank()) Muted(ui.version, theme, center = true)
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun NoticeLine(text: String, theme: LayoutTheme) {
    Text(text, color = theme.accent2, fontSize = 14.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
        .background(theme.surface).padding(12.dp))
}

@Composable
private fun ButtonRows(layout: AppLayout, buttons: List<LayoutButton>, ui: UiFlags, actions: ShopActions) {
    val theme = layout.theme
    if (buttons.isEmpty()) return
    // The first primary button stays a big button (for example «Перейти в личный кабинет»), the rest are rows.
    val head = buttons.takeWhile { it.style == "primary" }
    head.forEach { b -> ActionButton(b, theme, enabled = !ui.busy) { actions.run(b) } }
    val rest = buttons.drop(head.size)
    if (rest.isEmpty()) return
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(theme.radius.dp)).background(theme.surface)) {
        rest.forEachIndexed { i, b ->
            val toggled = when (b.action) { "push_toggle" -> ui.pushEnabled; "widget_toggle" -> ui.widgetEnabled; "vpn_mode" -> ui.engine; else -> null }
            val value = if (b.action == "language") ui.languageLabel else ""
            ActionRow(b, theme, value, toggled) { actions.run(b) }
            if (i < rest.lastIndex) HorizontalDivider(color = theme.surface2, modifier = Modifier.padding(start = 58.dp))
        }
    }
}

// ---------------------------------------------------------------- VPN

@Composable
private fun VpnScreen(layout: AppLayout, section: LayoutSection, base: String, data: ShopData, ui: UiFlags, actions: ShopActions) {
    val theme = layout.theme
    val buttons = visibleButtons(section, data)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        BrandTitle(layout.text("brand"), theme, Modifier.weight(1f))
        if (layout.feature("header_support") && layout.section("support") != null) IconButton(onClick = { actions.open("support") }) {
            Icon(Icons.Rounded.HeadsetMic, contentDescription = layout.section("support")?.title, tint = theme.text)
        }
        if (layout.feature("header_notifications") && layout.section("notifications") != null) IconButton(onClick = { actions.open("notifications") }) {
            Icon(Icons.Rounded.Notifications, contentDescription = layout.section("notifications")?.title, tint = theme.text)
        }
    }
    if (ui.offline) Muted(layout.text("offline"), theme, center = true)
    if (ui.notice.isNotBlank()) NoticeLine(ui.notice, theme)
    SectionBanner(base, section.banner, theme) { actions.link(it) }
    val connect = buttons.firstOrNull { it.action == "connect" }
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        val (status, color) = when (ui.vpn) {
            VpnState.ON -> layout.text("status_on") to theme.success
            VpnState.CONNECTING -> layout.text("status_connecting") to theme.accent2
            VpnState.OFF -> layout.text("status_off") to theme.muted
        }
        if (layout.feature("vpn_status")) StatusPill(status, color, theme)
        if (connect != null) {
            PowerButton(ui.vpn, theme, connect.label) { actions.run(connect) }
            Text(connect.label, color = theme.text, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        }
    }
    if (layout.feature("vpn_plan_card")) PlanSummary(layout, data, actions)
    // «Розыгрыш» banner like Lagom: shown while a giveaway is open and the customer has not joined.
    val promo = data.openGiveaway()
    val promoSection = layout.sections.firstOrNull { it.kind == "giveaways" }
    if (layout.feature("home_promo") && promo != null && promoSection != null) PromoCard(layout, promo) { actions.open(promoSection.id) }
    val location = buttons.firstOrNull { it.action == "open" && layout.section(it.target)?.kind == "locations" }
    val locationCard = location != null && layout.feature("vpn_location_card")
    if (locationCard) LocationCard(layout, data) { actions.run(location!!) }
    buttons.filter { it != connect && (it != location || !locationCard) }.forEach { b -> ActionButton(b, theme, enabled = !ui.busy) { actions.run(b) } }
}

@Composable
private fun BrandTitle(brand: String, theme: LayoutTheme, modifier: Modifier) {
    // «Корги VPN»: the last word in the accent colour and bold, like «ОгоньVPN».
    val words = brand.trim().split(" ")
    val text = buildAnnotatedString {
        if (words.size > 1) {
            withStyle(SpanStyle(color = theme.text, fontWeight = FontWeight.Light)) { append(words.dropLast(1).joinToString(" ") + " ") }
            withStyle(SpanStyle(color = theme.accent, fontWeight = FontWeight.Black)) { append(words.last()) }
        } else withStyle(SpanStyle(color = theme.accent, fontWeight = FontWeight.Black)) { append(brand) }
    }
    Text(text, fontSize = 30.sp, modifier = modifier)
}

@Composable
private fun PlanSummary(layout: AppLayout, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    val used = data.traffic.optLong("traffic_used_bytes", 0)
    val limit = if (data.traffic.isNull("traffic_limit_bytes")) 0L else data.traffic.optLong("traffic_limit_bytes", 0)
    val trafficValue = when {
        !data.subscribed -> layout.text("no_subscription")
        limit <= 0 -> layout.text("unlimited")
        else -> "${formatBytes((limit - used).coerceAtLeast(0))} / ${formatBytes(limit)}"
    }
    val progress = if (data.subscribed && limit > 0) (limit - used).toFloat() / limit else null
    Card(theme, onClick = { if (layout.section("subscription") != null) actions.open("subscription") }) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(data.subscription?.optString("name").orEmpty().ifBlank { layout.text("no_subscription") }, color = theme.text,
                    fontWeight = FontWeight.Bold, fontSize = 17.sp)
                val days = data.daysLeft()
                if (data.subscribed && days != null) Text("${layout.text("until")} ${data.expiresDate()} · ${layout.text("days_left").replace("{n}", days.toString())}",
                    color = theme.muted, fontSize = 13.sp)
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth()) {
            Text(layout.text("traffic_left"), color = theme.muted, modifier = Modifier.weight(1f))
            Text(trafficValue, color = theme.text, fontWeight = FontWeight.Bold)
        }
        if (progress != null) {
            Spacer(Modifier.height(10.dp))
            Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(theme.surface2)) {
                Box(Modifier.fillMaxWidth(progress.coerceIn(0f, 1f)).height(6.dp).clip(RoundedCornerShape(3.dp)).background(theme.accent))
            }
        }
    }
}

@Composable
private fun LocationCard(layout: AppLayout, data: ShopData, onClick: () -> Unit) {
    val theme = layout.theme
    val rec = data.routing.optJSONObject("recommendation")
    Card(theme, onClick = onClick) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(52.dp).clip(CircleShape).background(theme.surface2), contentAlignment = Alignment.Center) {
                if (rec == null) Icon(Icons.Rounded.RocketLaunch, contentDescription = null, tint = theme.accent)
                else Text(flag(rec.optString("country")), fontSize = 26.sp)
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(rec?.optString("name")?.ifBlank { null } ?: layout.text("auto_location"), color = theme.text, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                Text(layout.section("locations")?.title.orEmpty(), color = theme.muted, fontSize = 13.sp)
            }
            LoadBars(5, theme.success, theme)
        }
    }
}

@Composable
private fun LoadBars(level: Int, color: Color, theme: LayoutTheme) {
    Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.Bottom,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(theme.surface2).padding(horizontal = 12.dp, vertical = 8.dp)) {
        for (i in 1..5) Box(Modifier.width(5.dp).height((6 + i * 3).dp).clip(RoundedCornerShape(2.dp)).background(if (i <= level) color else theme.muted.copy(alpha = 0.3f)))
    }
}

// ---------------------------------------------------------------- Locations

@Composable
private fun LocationsBody(layout: AppLayout, data: ShopData) {
    val theme = layout.theme
    val nodes = data.nodes()
    if (nodes.isEmpty()) { Muted(layout.text("offline"), theme, center = true); return }
    val busiest = nodes.maxOf { it.optInt("users_online", 0) }.coerceAtLeast(1)
    val rec = data.routing.optJSONObject("recommendation")?.optString("name")
    nodes.forEach { node ->
        val online = node.optString("status") == "online"
        val load = node.optInt("users_online", 0)
        // Fewer customers online on a node → more free bars.
        val level = if (!online) 0 else (5 - (load * 4 / busiest)).coerceIn(1, 5)
        Card(theme) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(flag(node.optString("country")), fontSize = 28.sp)
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(node.optString("name"), color = theme.text, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    if (node.optString("name") == rec) Text(layout.text("auto_location"), color = theme.accent, fontSize = 12.sp)
                }
                LoadBars(level, if (online) theme.success else theme.danger, theme)
            }
        }
    }
}

// ---------------------------------------------------------------- Premium

@Composable
private fun PremiumBody(layout: AppLayout, data: ShopData, ui: UiFlags, actions: ShopActions) {
    val theme = layout.theme
    val plans = (0 until data.plans.length()).mapNotNull { data.plans.optJSONObject(it) }
    if (plans.isEmpty()) return
    val base = plans.minByOrNull { it.optInt("duration_days", 30) }?.let { monthlyPrice(it) } ?: 0.0
    val selected = ui.selectedPlan.takeIf { id -> plans.any { it.optInt("id") == id } } ?: plans.first().optInt("id")
    plans.forEach { plan ->
        val id = plan.optInt("id")
        val chosen = id == selected
        val perMonth = monthlyPrice(plan)
        val discount = if (base > 0 && perMonth < base) ((1 - perMonth / base) * 100).toInt() else 0
        val shape = RoundedCornerShape(theme.radius.dp)
        Row(
            Modifier.fillMaxWidth().clip(shape).background(theme.surface)
                .border(if (chosen) 2.dp else 0.dp, if (chosen) theme.accent2 else Color.Transparent, shape)
                .clickable(role = Role.RadioButton) { actions.selectPlan(id) }.padding(18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(plan.optString("name"), color = theme.text, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                val details = listOfNotNull(
                    plan.optInt("device_limit").takeIf { it > 0 }?.let { "${layout.text("devices")}: $it" },
                    if (plan.isNull("traffic_limit_gb") || plan.optInt("traffic_limit_gb") == 0) layout.text("unlimited") else "${plan.optInt("traffic_limit_gb")} GB",
                )
                Text(details.joinToString(" · "), color = theme.muted, fontSize = 13.sp)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text("${plan.optString("final_price").ifBlank { plan.optString("price") }.removeSuffix(".00")} ₽", color = theme.accent2, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("%.0f %s".format(perMonth, layout.text("per_month")) + if (discount > 0) "  −$discount%" else "", color = theme.muted, fontSize = 13.sp)
            }
            Spacer(Modifier.width(12.dp))
            Icon(if (chosen) Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked, contentDescription = null,
                tint = if (chosen) theme.accent2 else theme.muted)
        }
    }
    Muted(layout.text("consent"), theme)
}

// ---------------------------------------------------------------- Subscription

@Composable
private fun SubscriptionBody(layout: AppLayout, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    Card(theme, onClick = { actions.run(LayoutButton("copy_id", "", "copy_id", "", "ghost", "copy", "any")) }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(layout.text("your_id"), color = theme.success, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Text(data.customerId.ifBlank { "—" }, color = theme.success, fontWeight = FontWeight.Bold)
            Icon(Icons.Rounded.ContentCopy, contentDescription = null, tint = theme.muted, modifier = Modifier.padding(start = 10.dp).size(18.dp))
        }
    }
    val sub = data.subscription
    Card(theme) {
        Text(sub?.optString("name").orEmpty().ifBlank { layout.text("no_subscription") }, color = theme.text, fontSize = 26.sp, fontWeight = FontWeight.Bold)
        val days = data.daysLeft()
        if (data.subscribed && days != null) Text("${layout.text("until")} ${data.expiresDate()} · ${layout.text("days_left").replace("{n}", days.toString())}", color = theme.muted)
        Spacer(Modifier.height(12.dp))
        val plan = data.currentPlan()
        InfoLine(layout.text("devices"), "${data.activeDevices()} / ${plan?.optInt("device_limit")?.takeIf { it > 0 } ?: "∞"}", theme)
        val limit = if (data.traffic.isNull("traffic_limit_bytes")) 0L else data.traffic.optLong("traffic_limit_bytes", 0)
        val used = data.traffic.optLong("traffic_used_bytes", 0)
        InfoLine(layout.text("traffic_left"), if (limit <= 0) layout.text("unlimited") else "${formatBytes((limit - used).coerceAtLeast(0))} / ${formatBytes(limit)}", theme)
        InfoLine(layout.text("servers"), "${data.nodes().count { it.optString("status") == "online" }}", theme)
    }
    // Several subscriptions: choose the one the app connects with.
    if (data.profiles.length() > 1) for (i in 0 until data.profiles.length()) {
        val p = data.profiles.optJSONObject(i) ?: continue
        Card(theme, onClick = { actions.selectSubscription(p.optInt("id")) }) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${p.optString("name")} · ${p.optString("plan")}", color = theme.text, modifier = Modifier.weight(1f))
                Icon(if (p.optBoolean("is_primary")) Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked, contentDescription = null,
                    tint = if (p.optBoolean("is_primary")) theme.accent else theme.muted)
            }
        }
    }
}

@Composable
private fun InfoLine(title: String, value: String, theme: LayoutTheme) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp).clip(RoundedCornerShape(14.dp)).background(theme.surface2).padding(14.dp)) {
        Text(title, color = theme.muted, modifier = Modifier.weight(1f))
        Text(value, color = theme.text, fontWeight = FontWeight.Bold)
    }
}

// ---------------------------------------------------------------- other sections

@Composable
private fun DevicesBody(layout: AppLayout, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    for (i in 0 until data.devices.length()) {
        val d = data.devices.optJSONObject(i) ?: continue
        Card(theme) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(d.optString("name").ifBlank { d.optString("platform") }, color = theme.text, fontWeight = FontWeight.Bold)
                    Text("${d.optString("platform")} · ${d.optString("status")}", color = theme.muted, fontSize = 13.sp)
                }
                if (d.optString("status") == "active") Text("✕", color = theme.danger, fontSize = 20.sp,
                    modifier = Modifier.clip(CircleShape).clickable { actions.revokeDevice(d.optInt("id")) }.padding(10.dp))
            }
        }
    }
}

@Composable
private fun FamilyBody(layout: AppLayout, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    val owned = data.family.optJSONArray("owned")
    if (owned != null) for (i in 0 until owned.length()) {
        val group = owned.optJSONObject(i) ?: continue
        Card(theme) {
            Text(group.optString("name"), color = theme.text, fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("${group.optInt("used")} / ${group.optInt("seats")}", color = theme.muted)
            group.optJSONObject("invite")?.optString("code")?.takeIf { it.isNotBlank() }?.let { Text(it, color = theme.accent2, fontWeight = FontWeight.Bold, fontSize = 20.sp) }
            val members = group.optJSONArray("members")
            if (members != null) for (m in 0 until members.length()) {
                val member = members.optJSONObject(m) ?: continue
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(member.optString("name"), color = theme.text, modifier = Modifier.weight(1f))
                    Text("✕", color = theme.danger, modifier = Modifier.clickable { actions.removeFamilyMember(member.optInt("id")) }.padding(8.dp))
                }
            }
        }
    }
    var code by remember { mutableStateOf("") }
    TextInput(code, { code = it }, layout.section("family")?.title.orEmpty() + " · код", theme)
    if (code.isNotBlank()) ActionButton(LayoutButton("join", "✓", "open", "", "secondary", "heart", "any"), theme) { actions.joinFamily(code.trim()); code = "" }
}

@Composable
private fun ReferralBody(layout: AppLayout, data: ShopData) {
    val theme = layout.theme
    Card(theme) {
        Text(data.user.optString("referral_code"), color = theme.accent2, fontSize = 24.sp, fontWeight = FontWeight.Bold)
        Text(data.user.optString("referral_balance").takeIf { it.isNotBlank() && it != "0" && it != "0.00" }?.let { "+$it ₽" }.orEmpty(), color = theme.success)
    }
    val contest = data.contest
    if (contest.optString("title").isNotBlank()) Card(theme) {
        Text("🏆 ${contest.optString("title")}", color = theme.text, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        Text("${layout.text("contest_until")} ${contest.optString("ends_at").take(10)}", color = theme.muted)
        val top = contest.optJSONArray("top") ?: JSONArray()
        for (i in 0 until top.length()) {
            val row = top.optJSONObject(i) ?: continue
            InfoLine("${row.optInt("place")}. ${row.optString("name")}", row.optInt("score").toString(), theme)
        }
        val me = contest.optJSONObject("me")
        Text(if (me != null) layout.text("contest_me").replace("{place}", me.optInt("place").toString()).replace("{score}", me.optInt("score").toString())
             else layout.text("contest_join"), color = theme.success, fontWeight = FontWeight.Bold)
    }
}

/** «Моя статистика» and one-click offers under the subscription card (v28.37). */
@Composable
private fun InsightsCards(layout: AppLayout, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    val s = data.stats
    if (s.length() > 0) Card(theme) {
        Text(layout.text("stats_title"), color = theme.text, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        InfoLine(layout.text("stats_days"), "${s.optInt("days_with_us")} ${layout.text("days_short")}", theme)
        InfoLine(layout.text("stats_paid"), "${s.optInt("days_paid")} ${layout.text("days_short")}", theme)
        if (!s.isNull("traffic_used_gb")) InfoLine(layout.text("stats_traffic"), "${s.optDouble("traffic_used_gb")} GB" +
            (if (s.isNull("traffic_limit_gb")) "" else " / ${s.optDouble("traffic_limit_gb")} GB"), theme)
        if (!s.isNull("traffic_lifetime_gb")) InfoLine(layout.text("stats_lifetime"), "${s.optDouble("traffic_lifetime_gb")} GB", theme)
        if (!s.isNull("traffic_30d_gb") && s.has("traffic_30d_gb")) InfoLine(layout.text("stats_month"), "${s.optDouble("traffic_30d_gb")} GB", theme)
        InfoLine(layout.text("stats_avoided"), s.optInt("blocked_servers_avoided").toString(), theme)
    }
    if (data.upsell.length() > 0) Card(theme) {
        Text(layout.text("upsell_title"), color = theme.text, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        for (i in 0 until data.upsell.length()) {
            val offer = data.upsell.optJSONObject(i) ?: continue
            Text(offer.optString("title"), color = theme.text, fontWeight = FontWeight.Bold)
            Muted(offer.optString("reason"), theme)
            ActionButton(LayoutButton("upsell_$i", "${offer.optString("price")} ₽", "refresh", "", "primary", "wallet", "any"), theme) { actions.buyOffer(offer) }
        }
    }
}

@Composable
private fun WalletBody(layout: AppLayout, data: ShopData, ui: UiFlags, actions: ShopActions) {
    val theme = layout.theme
    Card(theme) {
        Text("${data.user.optString("wallet_balance", "0")} ₽", color = theme.text, fontSize = 34.sp, fontWeight = FontWeight.Bold)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("100", "300", "500", "1000").forEach { value ->
            val chosen = value == ui.topupAmount
            Text("$value ₽", color = if (chosen) Color(0xFF1A0F05) else theme.text, fontWeight = FontWeight.Bold,
                modifier = Modifier.clip(RoundedCornerShape(50)).background(if (chosen) theme.accent else theme.surface)
                    .clickable { actions.setTopupAmount(value) }.padding(horizontal = 14.dp, vertical = 10.dp))
        }
    }
    TextInput(ui.topupAmount, { actions.setTopupAmount(it.filter(Char::isDigit).take(6)) }, "₽", theme)
}

@Composable
private fun NotificationsBody(layout: AppLayout, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    for (i in 0 until data.notifications.length()) {
        val n = data.notifications.optJSONObject(i) ?: continue
        Card(theme, onClick = if (!n.optBoolean("read")) ({ actions.markRead(n.optInt("id")) }) else null) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (!n.optBoolean("read")) Box(Modifier.size(8.dp).clip(CircleShape).background(theme.accent))
                Spacer(Modifier.width(8.dp))
                Text(n.optString("title"), color = theme.text, fontWeight = FontWeight.Bold)
            }
            Text(n.optString("body"), color = theme.muted, fontSize = 14.sp)
        }
    }
}

@Composable
private fun StatusBody(layout: AppLayout, data: ShopData) {
    val theme = layout.theme
    val level = data.status.optString("status", "unknown")
    val color = when (level) { "ok" -> theme.success; "degraded" -> theme.accent2; "down" -> theme.danger; else -> theme.muted }
    val servers = data.status.optJSONObject("servers") ?: JSONObject()
    Card(theme) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(12.dp).clip(CircleShape).background(color))
            Spacer(Modifier.width(10.dp))
            Text("${layout.text("servers")}: ${servers.optInt("online")} / ${servers.optInt("total")}", color = theme.text, fontWeight = FontWeight.Bold)
        }
    }
    val countries = data.status.optJSONArray("countries")
    if (countries != null) for (i in 0 until countries.length()) {
        val c = countries.optJSONObject(i) ?: continue
        InfoLine("${flag(c.optString("country"))}  ${c.optString("country")}", "${c.optInt("online")} / ${c.optInt("total")}", theme)
    }
    val incidents = data.status.optJSONArray("incidents")
    if (incidents != null) for (i in 0 until incidents.length()) {
        val inc = incidents.optJSONObject(i) ?: continue
        NoticeLine("${inc.optString("title")} · ${inc.optString("since")}", theme)
    }
}

@Composable
private fun SecurityBody(layout: AppLayout, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    for (i in 0 until data.passkeys.length()) {
        val key = data.passkeys.optJSONObject(i) ?: continue
        Card(theme) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(key.optString("name"), color = theme.text, modifier = Modifier.weight(1f))
                Text("✕", color = theme.danger, modifier = Modifier.clickable { actions.deletePasskey(key.optInt("id")) }.padding(8.dp))
            }
        }
    }
}

@Composable
fun TextInput(value: String, onChange: (String) -> Unit, label: String, theme: LayoutTheme, secret: Boolean = false, singleLine: Boolean = true) {
    OutlinedTextField(
        value, onChange, label = { Text(label) }, singleLine = singleLine,
        visualTransformation = if (secret) androidx.compose.ui.text.input.PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth(),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = theme.accent, unfocusedBorderColor = theme.surface2, focusedLabelColor = theme.accent,
            unfocusedLabelColor = theme.muted, focusedTextColor = theme.text, unfocusedTextColor = theme.text, cursorColor = theme.accent,
            focusedContainerColor = theme.surface, unfocusedContainerColor = theme.surface,
        ),
    )
}

/** QR code of the subscription for another device. */
@Composable
fun QrCard(data: ShopData, theme: LayoutTheme) {
    val qr = data.qr ?: return
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Image(qr, contentDescription = "QR", modifier = Modifier.size(240.dp).clip(RoundedCornerShape(theme.radius.dp)).background(Color.White).padding(12.dp))
    }
}

// ---------------------------------------------------------------- documents

/** «Информация»: the documents the shop published in «Бот и кабинет → Документы». */
@Composable
private fun InfoBody(layout: AppLayout, base: String, data: ShopData, actions: ShopActions) {
    val theme = layout.theme
    if (data.docs.length() == 0) { Muted(layout.text("offline"), theme, center = true); return }
    for (i in 0 until data.docs.length()) {
        val doc = data.docs.optJSONObject(i) ?: continue
        Card(theme, onClick = { actions.openDocument(doc.optString("kind")) }) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(doc.optString("title"), color = theme.text, fontWeight = FontWeight.Bold, fontSize = 17.sp, modifier = Modifier.weight(1f))
                Text("›", color = theme.muted, fontSize = 22.sp)
            }
        }
    }
}

@Composable
private fun PromoCard(layout: AppLayout, row: JSONObject, onOpen: () -> Unit) {
    val theme = layout.theme
    Card(theme, onClick = onOpen) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("🎁", fontSize = 30.sp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(row.optString("title"), color = theme.accent, fontWeight = FontWeight.Black, fontSize = 17.sp)
                Text(prizeLine(layout, row), color = theme.muted, fontSize = 13.sp)
            }
            Text(layout.text("giveaway_join"), color = theme.accent, fontWeight = FontWeight.Bold)
        }
    }
}

private fun prizeLine(layout: AppLayout, row: JSONObject): String {
    val prizes = row.optJSONArray("prizes") ?: JSONArray()
    var best = 0.0
    for (i in 0 until prizes.length()) best = maxOf(best, prizes.optJSONObject(i)?.optString("amount")?.toDoubleOrNull() ?: 0.0)
    val until = row.optString("ends_at").take(10)
    val prize = if (best > 0) "🏆 ${"%.0f".format(best)} ${row.optString("currency")}" else ""
    return listOf(prize, if (until.isNotBlank()) "${layout.text("until")} $until" else "").filter { it.isNotBlank() }.joinToString(" · ")
}

@Composable
private fun GiveawaysBody(layout: AppLayout, data: ShopData, ui: UiFlags, actions: ShopActions) {
    val theme = layout.theme
    if (data.giveaways.length() == 0) { Muted(layout.text("giveaway_none"), theme, center = true); return }
    for (i in 0 until data.giveaways.length()) {
        val row = data.giveaways.optJSONObject(i) ?: continue
        Card(theme) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(row.optString("title"), color = theme.text, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                if (row.optString("description").isNotBlank()) Text(row.optString("description"), color = theme.muted, fontSize = 14.sp)
                Text(prizeLine(layout, row), color = theme.accent2, fontSize = 13.sp)
                val mine = row.optJSONObject("my_entry")
                when {
                    mine != null && mine.optString("outcome") == "won" ->
                        Text(layout.text("giveaway_won").replace("{amount}", "${mine.optString("reward_amount")} ${row.optString("currency")}"), color = theme.success, fontWeight = FontWeight.Bold)
                    mine != null && mine.optString("outcome") in setOf("lost", "ineligible") -> Muted(layout.text("giveaway_lost"), theme)
                    mine != null -> Muted(layout.text("giveaway_entered"), theme)
                    row.optString("phase") == "open" -> ActionButton(LayoutButton("giveaway_${row.optInt("id")}", layout.text("giveaway_join"),
                        "refresh", "", "primary", "trophy", "any"), theme, enabled = !ui.busy) { actions.enterGiveaway(row.optInt("id")) }
                    else -> Muted(layout.text("giveaway_closed"), theme)
                }
            }
        }
    }
}

/** One document with its banner: ``## heading``, ``- item``, ``**bold**``; FAQ as questions that open. */
@Composable
fun DocumentScreen(layout: AppLayout, base: String, doc: JSONObject, onBack: () -> Unit, onLink: (String) -> Unit) {
    val theme = layout.theme
    Column(
        Modifier.fillMaxSize().background(theme.background).statusBarsPadding().verticalScroll(rememberScrollState())
            .padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("←", color = theme.text, fontSize = 22.sp, modifier = Modifier.clip(CircleShape).clickable(onClick = onBack).padding(8.dp))
        Text(doc.optString("title"), color = theme.text, fontSize = 26.sp, fontWeight = FontWeight.Bold)
        val banner = doc.optString("banner")
        if (banner.isNotBlank()) SectionBanner(base, LayoutBanner(banner, ""), theme, onLink)
        val body = doc.optString("body")
        if (body.isNotBlank()) Card(theme) { DocumentText(body, theme) }
        val items = doc.optJSONArray("items")
        if (items != null) for (i in 0 until items.length()) {
            val item = items.optJSONObject(i) ?: continue
            var open by remember(i) { mutableStateOf(false) }
            Card(theme, onClick = { open = !open }) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(item.optString("question"), color = theme.text, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    Text(if (open) "−" else "+", color = theme.accent, fontSize = 22.sp)
                }
                if (open) DocumentText(item.optString("answer"), theme)
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun DocumentText(text: String, theme: LayoutTheme) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        text.split("\n").forEach { raw ->
            val line = raw.trimEnd()
            when {
                line.isBlank() -> Spacer(Modifier.height(4.dp))
                line.startsWith("## ") -> Text(rich(line.removePrefix("## "), theme), color = theme.text, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                line.startsWith("- ") -> Text(rich("•  " + line.removePrefix("- "), theme), color = theme.text, fontSize = 15.sp, lineHeight = 21.sp)
                else -> Text(rich(line, theme), color = theme.text, fontSize = 15.sp, lineHeight = 21.sp)
            }
        }
    }
}

private fun rich(text: String, theme: LayoutTheme) = buildAnnotatedString {
    var rest = text
    while (true) {
        val start = rest.indexOf("**")
        val end = if (start >= 0) rest.indexOf("**", start + 2) else -1
        if (start < 0 || end < 0) { append(rest); break }
        append(rest.substring(0, start))
        withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = theme.accent2)) { append(rest.substring(start + 2, end)) }
        rest = rest.substring(end + 2)
    }
}
