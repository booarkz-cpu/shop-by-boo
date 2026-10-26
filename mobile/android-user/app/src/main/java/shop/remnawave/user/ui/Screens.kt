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
import org.json.JSONObject

/** Buttons of a section visible to this customer (audience «с подпиской» / «без подписки»). */
fun visibleButtons(section: LayoutSection, data: ShopData): List<LayoutButton> = section.buttons.filter {
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
                "subscription" -> SubscriptionBody(layout, data, actions)
                "devices" -> DevicesBody(layout, data, actions)
                "family" -> FamilyBody(layout, data, actions)
                "referral" -> ReferralBody(layout, data)
                "wallet" -> WalletBody(layout, data, ui, actions)
                "notifications" -> NotificationsBody(layout, data, actions)
                "status" -> StatusBody(layout, data)
                "security" -> SecurityBody(layout, data, actions)
                else -> {}
            }
            if (section.body.isNotBlank()) Card(theme) { Text(section.body, color = theme.text, fontSize = 15.sp, lineHeight = 22.sp) }
            val buttons = visibleButtons(section, data)
            if (section.kind == "settings" || section.kind == "support") {
                ButtonRows(layout, buttons, ui, actions)
            } else {
                buttons.forEach { b -> ActionButton(b, theme, enabled = !ui.busy) { actions.run(b) } }
            }
            if (section.kind == "settings" && ui.version.isNotBlank()) Muted(ui.version, theme, center = true)
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
            val toggled = when (b.action) { "push_toggle" -> ui.pushEnabled; "widget_toggle" -> ui.widgetEnabled; else -> null }
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
        if (layout.section("support") != null) IconButton(onClick = { actions.open("support") }) {
            Icon(Icons.Rounded.HeadsetMic, contentDescription = layout.section("support")?.title, tint = theme.text)
        }
        if (layout.section("notifications") != null) IconButton(onClick = { actions.open("notifications") }) {
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
        StatusPill(status, color, theme)
        if (connect != null) {
            PowerButton(ui.vpn, theme, connect.label) { actions.run(connect) }
            Text(connect.label, color = theme.text, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        }
    }
    PlanSummary(layout, data, actions)
    val location = buttons.firstOrNull { it.action == "open" && layout.section(it.target)?.kind == "locations" }
    if (location != null) LocationCard(layout, data) { actions.run(location) }
    buttons.filter { it != connect && it != location }.forEach { b -> ActionButton(b, theme, enabled = !ui.busy) { actions.run(b) } }
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
