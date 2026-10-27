import Combine
import LocalAuthentication
import SwiftUI
import UIKit

/// The customer app. Every screen, button, banner and colour comes from the layout the shop
/// administrator edits («Приложения: экраны и кнопки»); the bundled default is drawn until the
/// shop answers and whenever it is unreachable.
struct UserRootView: View {
    @AppStorage("shop_lang") private var lang = UserRootView.detectLanguage()
    @AppStorage("shop_base") private var base = ""
    @State private var token = SessionKeychain.load(baseKey: "shop_base", legacyKey: "shop_token")
    @Environment(\.scenePhase) private var scenePhase
    @State private var authenticationContext: LAContext?
    @State private var email = ""
    @State private var password = ""
    @State private var tab = "vpn"
    @State private var notice = ""
    @State private var busy = false
    @State private var offline = false
    @State private var unlocked = false
    @State private var layout = AppLayout()
    @State private var data = ShopData()
    @State private var vpn: VpnState = .off
    @State private var connectingSince: Date?
    @State private var selectedPlan = 0
    @State private var topupAmount = "300"
    @State private var familyCode = ""
    @State private var sheet = ""
    @State private var sheetText = ""
    @State private var sheetText2 = ""
    /// A document opened from «Информация» or a «Открыть документ» button.
    @State private var openDoc: [String: Any]?
    /// Shop logo from «Android и iOS → логотип» (GET /api/public/apps).
    @State private var logo: UIImage?
    @ObservedObject private var push = PushCenter.shared
    @State private var pushEnabled = PushCenter.shared.enabled
    /// Sign-in methods the shop has configured (GET /api/public/app-login/methods).
    @State private var methods: [String: Any] = [:]
    private let vpnTimer = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    private static func detectLanguage() -> String {
        let code = Locale.preferredLanguages.first?.lowercased() ?? "ru"
        if code.hasPrefix("uk") { return "uk" }
        if code.hasPrefix("en") { return "en" }
        return "ru"
    }
    private static func nextLanguage(_ current: String) -> String {
        switch current { case "ru": return "en"; case "en": return "uk"; default: return "ru" }
    }
    private static func languageLabel(_ current: String) -> String {
        switch current { case "ru": return "EN"; case "en": return "UK"; default: return "RU" }
    }
    private static func languageName(_ current: String) -> String {
        switch current { case "en": return "English"; case "uk": return "Українська"; default: return "Русский" }
    }

    private var strings: [String: String] { loadStrings(lang) }
    // A string replaced in the admin panel («Строки приложения») wins over the bundled one.
    private func t(_ key: String) -> String { layout.strings[key] ?? strings[key] ?? key }
    private var theme: LayoutTheme { layout.theme }
    private var appVersion: String { "Corgi Lusi " + (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "") }

    var body: some View {
        ZStack {
            theme.background.ignoresSafeArea()
            if token.isEmpty { login } else if !unlocked { lock } else { home }
        }
        .preferredColorScheme(.dark)
        .overlay { if scenePhase != .active { Color.black.ignoresSafeArea() } }
        .sheet(isPresented: Binding(get: { !sheet.isEmpty }, set: { if !$0 { sheet = "" } })) { sheetView }
        .onOpenURL { url in
            guard let link = LoginLink.parse(url) else { return }
            #if DEBUG
            if DemoMode.enabled { return }
            #endif
            if !token.isEmpty { notice = t("login_link_signed_in"); return }
            redeem(link)
        }
        .onAppear {
            CorgiTunnelManager.shared.load()
            if !bakedShopURL.isEmpty { base = bakedShopURL }
            layout = LayoutStore.cached(base: base, lang: lang) ?? LayoutStore.bundled(lang)
            #if DEBUG
            if DemoMode.enabled { loadDemo(); return }
            #endif
            loadLayout()
            if let origin = try? normalizeBase(base) {
                CorgiAnalytics.install(base: origin)
                track(token.isEmpty ? "sign_in_view" : "open")
            }
            if !token.isEmpty && !unlocked { unlockSavedSession() }
        }
        .onReceive(vpnTimer) { _ in
            #if DEBUG
            if DemoMode.enabled { return }
            #endif
            if CorgiTunnelManager.available {
                switch CorgiTunnelManager.shared.status {
                case .connected: vpn = .on; connectingSince = nil
                case .connecting, .reasserting: vpn = .connecting
                default:
                    if vpn == .connecting, let problem = CorgiTunnelManager.shared.lastError { notice = problem }
                    vpn = .off; connectingSince = nil
                }
                return
            }
            let on = VpnClients.vpnActive()
            if on { vpn = .on; connectingSince = nil }
            else if vpn == .on { vpn = .off }
            // The tunnel is switched on in the client; without it the status returns to «off» in a minute.
            else if vpn == .connecting, let since = connectingSince, Date().timeIntervalSince(since) > 60 { vpn = .off; connectingSince = nil }
        }
        .onChange(of: token) { value in
            if !value.isEmpty { track("sign_in") }
            if value.isEmpty { SessionKeychain.clear() }
            else if unlocked { refresh() }
        }
        .onChange(of: scenePhase) { phase in
            if phase == .background {
                authenticationContext?.invalidate()
                authenticationContext = nil
                unlocked = false
            }
        }
        .onChange(of: unlocked) { value in if value && !token.isEmpty { refresh() } }
        .onChange(of: lang) { _ in
            layout = LayoutStore.cached(base: base, lang: lang) ?? LayoutStore.bundled(lang)
            loadLayout()
            if !token.isEmpty && unlocked { refresh() }
        }
        .onChange(of: tab) { value in track("screen", value) }
        .onChange(of: vpn) { value in if value == .on { track("connected") } }
        .onChange(of: push.openSection) { section in
            if let section, layout.section(section) != nil { tab = section; openDoc = nil; push.openSection = nil }
        }
        .onChange(of: push.openNotifications) { open in
            if open, layout.section("notifications") != nil { tab = "notifications"; push.openNotifications = false }
        }
    }

    // MARK: sign-in and lock

    private var login: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    if let logo { Image(uiImage: logo).resizable().scaledToFit().frame(width: 44, height: 44) }
                    Text(layout.text("brand")).font(.system(size: 30, weight: .black)).foregroundStyle(theme.accent)
                    Spacer()
                    if layout.feature("language_switch") {
                        Button(Self.languageLabel(lang)) { lang = Self.nextLanguage(lang) }.foregroundStyle(theme.muted)
                    }
                }
                if layout.feature("login_banner") {
                    SectionBannerView(base: base, banner: layout.sections.first { $0.kind == "vpn" }?.banner, theme: theme) { _ in }
                }
                Text(t("welcome")).font(.system(size: 26, weight: .bold)).foregroundStyle(theme.text)
                Text(t("tagline")).foregroundStyle(theme.muted)
                if !notice.isEmpty { Text(notice).foregroundStyle(theme.accent2) }
                if bakedShopURL.isEmpty { InputField(title: t("server"), text: $base, theme: theme) }
                // Quick sign-in: Telegram bot link and OAuth providers enabled on the shop.
                if layout.feature("login_quick") {
                    if methods["telegram"] as? Bool == true {
                        ActionButtonView(button: LayoutButton(id: "login_telegram", label: t("login_telegram"), action: "refresh", target: "", style: "primary", icon: "send", audience: "any"), theme: theme, enabled: !busy) {
                            if let link = methods["telegram_url"] as? String, link.hasPrefix("https://t.me/") { openExternal(link) }
                        }
                    }
                    ForEach(["yandex", "vk", "google"].filter { methods[$0] as? Bool == true }, id: \.self) { provider in
                        ActionButtonView(button: LayoutButton(id: "login_\(provider)", label: t("login_\(provider)"), action: "refresh", target: "", style: "secondary", icon: "user", audience: "any"), theme: theme, enabled: !busy) { openOAuth(provider) }
                    }
                    if ["telegram", "yandex", "vk", "google"].contains(where: { methods[$0] as? Bool == true }) {
                        Text(t("login_or_email")).foregroundStyle(theme.muted)
                    }
                }
                InputField(title: t("email"), text: $email, theme: theme)
                InputField(title: t("password"), text: $password, theme: theme, secure: true)
                ActionButtonView(button: LayoutButton(id: "sign_in", label: t("sign_in"), action: "refresh", target: "", style: "primary", icon: "user", audience: "any"), theme: theme, enabled: !busy) { authenticate("/api/auth/login") }
                if layout.feature("login_sign_up") { ActionButtonView(button: LayoutButton(id: "sign_up", label: t("sign_up"), action: "refresh", target: "", style: "secondary", icon: "plus", audience: "any"), theme: theme, enabled: !busy) { authenticate("/api/auth/register") } }
                // Discoverable passkey: only the shop address is needed.
                if layout.feature("login_passkey") {
                    ActionButtonView(button: LayoutButton(id: "passkey", label: t("passkey_sign_in"), action: "refresh", target: "", style: "ghost", icon: "key", audience: "any"), theme: theme, enabled: !busy) { signInWithPasskey() }
                }
            }
            .padding(22)
        }
        .onChange(of: base) { _ in loadLayout(); loadLogo(); loadMethods() }
        .onAppear { loadLogo(); loadMethods() }
    }

    private var lock: some View {
        VStack(spacing: 14) {
            Text(layout.text("brand")).font(.system(size: 34, weight: .black)).foregroundStyle(theme.accent)
            if !notice.isEmpty { Text(notice).foregroundStyle(theme.accent2) }
            ActionButtonView(button: LayoutButton(id: "unlock", label: t("unlock"), action: "refresh", target: "", style: "primary", icon: "lock", audience: "any"), theme: theme) { unlockSavedSession() }
            ActionButtonView(button: LayoutButton(id: "sign_out", label: t("sign_out"), action: "sign_out", target: "", style: "ghost", icon: "logout", audience: "any"), theme: theme) { signOut() }
        }
        .padding(32)
    }

    // MARK: sections

    private var currentSection: LayoutSection? {
        layout.section(tab) ?? layout.sections.first { $0.kind == "vpn" } ?? layout.sections.first
    }

    private var home: some View {
        VStack(spacing: 0) {
            if let doc = openDoc {
                DocumentView(layout: layout, base: base, doc: doc, onBack: { openDoc = nil }, onLink: { openExternal($0) })
            } else {
            ZStack(alignment: .topLeading) {
                ScrollView {
                    VStack(spacing: 14) {
                        if let section = currentSection { sectionView(section) }
                    }
                    .padding(.horizontal, 18).padding(.vertical, 12).padding(.bottom, 24)
                }
                .refreshable { refresh() }
                if let section = currentSection, !section.tab {
                    Button { tab = layout.tabs.first { layout.section($0)?.kind == "vpn" } ?? layout.tabs.first ?? "vpn" } label: {
                        Image(systemName: "chevron.left").font(.system(size: 20, weight: .semibold)).foregroundStyle(theme.text).padding(14)
                    }
                    .accessibilityLabel("Назад")
                }
            }
            }
            BottomBar(layout: layout, current: currentSection?.tab == true ? currentSection?.id ?? "" : "") { id in tab = id; openDoc = nil; notice = "" }
        }
    }

    private func visible(_ section: LayoutSection) -> [LayoutButton] {
        // The iOS app has no home screen widget: its switch is Android-only.
        section.buttons.filter { $0.action != "widget_toggle" }.filter { b in
            switch b.audience { case "subscribed": return data.subscribed; case "unsubscribed": return !data.subscribed; default: return true }
        }
    }

    @ViewBuilder private func sectionView(_ section: LayoutSection) -> some View {
        if section.kind == "vpn" {
            vpnSection(section)
        } else {
            Text(section.title).font(.system(size: 28, weight: .bold)).foregroundStyle(theme.text).frame(maxWidth: .infinity).padding(.top, 8)
            if offline { Text(layout.text("offline")).foregroundStyle(theme.muted).font(.footnote) }
            if !notice.isEmpty { noticeLine }
            SectionBannerView(base: base, banner: section.banner, theme: theme) { openExternal($0) }
            if !section.subtitle.isEmpty { Text(section.subtitle).foregroundStyle(theme.muted).font(.subheadline).frame(maxWidth: .infinity, alignment: .leading) }
            switch section.kind {
            case "locations": locationsBody
            case "premium": premiumBody
            case "subscription": subscriptionBody
            case "devices": devicesBody
            case "family": familySection
            case "referral": referralBody
            case "wallet": walletBody
            case "notifications": notificationsBody
            case "status": statusSection
            case "security": securityBody
            case "info": infoBody
            case "giveaways": giveawaysBody
            default: EmptyView()
            }
            if !section.body.isEmpty { CardView(theme: theme) { Text(section.body).foregroundStyle(theme.text) } }
            let buttons = visible(section)
            if section.kind == "settings" || section.kind == "support" {
                rows(buttons)
                if section.kind == "settings" && layout.feature("settings_version") { Text(appVersion).font(.footnote).foregroundStyle(theme.muted) }
            } else {
                ForEach(buttons) { b in ActionButtonView(button: b, theme: theme, enabled: !busy) { run(b) } }
            }
        }
    }

    private var noticeLine: some View {
        Text(notice).font(.subheadline).foregroundStyle(theme.accent2).frame(maxWidth: .infinity, alignment: .leading)
            .padding(12).background(RoundedRectangle(cornerRadius: 12).fill(theme.surface))
    }

    @ViewBuilder private func rows(_ buttons: [LayoutButton]) -> some View {
        let head = Array(buttons.prefix { $0.style == "primary" })
        let rest = Array(buttons.dropFirst(head.count))
        ForEach(head) { b in ActionButtonView(button: b, theme: theme, enabled: !busy) { run(b) } }
        if !rest.isEmpty {
            VStack(spacing: 0) {
                ForEach(Array(rest.enumerated()), id: \.element.id) { i, b in
                    ActionRowView(button: b, theme: theme, value: b.action == "language" ? Self.languageName(lang) : "",
                                  toggled: b.action == "push_toggle" ? pushEnabled : nil) { run(b) }
                    if i < rest.count - 1 { Divider().background(theme.surface2).padding(.leading, 58) }
                }
            }
            .background(RoundedRectangle(cornerRadius: theme.radius).fill(theme.surface))
        }
    }

    @ViewBuilder private func vpnSection(_ section: LayoutSection) -> some View {
        let buttons = visible(section)
        let connect = buttons.first { $0.action == "connect" }
        let location = buttons.first { $0.action == "open" && layout.section($0.target)?.kind == "locations" }
        HStack {
            BrandTitle(brand: layout.text("brand"), theme: theme)
            Spacer()
            if layout.feature("header_support"), let support = layout.section("support") {
                Button { tab = "support" } label: { Image(systemName: "headphones").font(.system(size: 22)).foregroundStyle(theme.text) }.accessibilityLabel(support.title)
            }
            if layout.feature("header_notifications"), let notifications = layout.section("notifications") {
                Button { tab = "notifications" } label: { Image(systemName: "bell.fill").font(.system(size: 22)).foregroundStyle(theme.text) }.accessibilityLabel(notifications.title)
            }
        }
        if offline { Text(layout.text("offline")).foregroundStyle(theme.muted).font(.footnote) }
        if !notice.isEmpty { noticeLine }
        SectionBannerView(base: base, banner: section.banner, theme: theme) { openExternal($0) }
        VStack(spacing: 10) {
            if layout.feature("vpn_status") {
            switch vpn {
            case .on: StatusPill(text: layout.text("status_on"), color: theme.success, theme: theme)
            case .connecting: StatusPill(text: layout.text("status_connecting"), color: theme.accent2, theme: theme)
            case .off: StatusPill(text: layout.text("status_off"), color: theme.muted, theme: theme)
            }
            }
            if let connect {
                PowerButton(state: vpn, theme: theme, label: connect.label) { run(connect) }
                Text(connect.label).font(.system(size: 18, weight: .bold)).foregroundStyle(theme.text)
            }
        }
        if layout.feature("vpn_plan_card") { planSummary }
        // «Розыгрыш» banner like Lagom: shown while a giveaway is open and the customer has not joined.
        if layout.feature("home_promo"), let promo = data.openGiveaway, let target = layout.sections.first(where: { $0.kind == "giveaways" }) {
            Button { track("promo_tap"); tab = target.id } label: {
                CardView(theme: theme) {
                    HStack(spacing: 12) {
                        Text("🎁").font(.system(size: 30))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(jsonText(promo["title"])).font(.system(size: 17, weight: .black)).foregroundStyle(theme.accent)
                            Text(prizeLine(promo)).font(.footnote).foregroundStyle(theme.muted)
                        }
                        Spacer()
                        Text(layout.text("giveaway_join")).bold().foregroundStyle(theme.accent)
                    }
                }
            }
            .buttonStyle(.plain)
        }
        let showLocation = location != nil && layout.feature("vpn_location_card")
        if showLocation, let location {
            Button { run(location) } label: { locationCard }.buttonStyle(.plain)
        }
        ForEach(buttons.filter { $0 != connect && ($0 != location || !showLocation) }) { b in ActionButtonView(button: b, theme: theme, enabled: !busy) { run(b) } }
    }

    private var trafficLeft: (String, Double?) {
        let used = Double(jsonInt(data.traffic["traffic_used_bytes"]) ?? 0)
        let limit = Double(jsonInt(data.traffic["traffic_limit_bytes"]) ?? 0)
        if !data.subscribed { return (layout.text("no_subscription"), nil) }
        if limit <= 0 { return (layout.text("unlimited"), nil) }
        return ("\(formatBytes(max(limit - used, 0))) / \(formatBytes(limit))", max(limit - used, 0) / limit)
    }

    private var untilLine: String {
        guard data.subscribed, let days = data.daysLeft else { return "" }
        return "\(layout.text("until")) \(data.expires) · \(layout.text("days_left").replacingOccurrences(of: "{n}", with: String(days)))"
    }

    private var planSummary: some View {
        Button { if layout.section("subscription") != nil { tab = "subscription" } } label: {
            CardView(theme: theme) {
                Text(jsonText(data.subscription?["name"]).isEmpty ? layout.text("no_subscription") : jsonText(data.subscription?["name"]))
                    .font(.system(size: 17, weight: .bold)).foregroundStyle(theme.text)
                if !untilLine.isEmpty { Text(untilLine).font(.footnote).foregroundStyle(theme.muted) }
                HStack {
                    Text(layout.text("traffic_left")).foregroundStyle(theme.muted)
                    Spacer()
                    Text(trafficLeft.0).fontWeight(.bold).foregroundStyle(theme.text)
                }
                if let progress = trafficLeft.1 {
                    ProgressView(value: min(max(progress, 0), 1)).tint(theme.accent)
                }
            }
        }
        .buttonStyle(.plain)
    }

    private var locationCard: some View {
        let rec = data.routing["recommendation"] as? [String: Any]
        return CardView(theme: theme) {
            HStack(spacing: 14) {
                ZStack {
                    Circle().fill(theme.surface2).frame(width: 52, height: 52)
                    if let rec { Text(flagEmoji(jsonText(rec["country"]))).font(.system(size: 26)) }
                    else { Image(systemName: "bolt.fill").foregroundStyle(theme.accent) }
                }
                VStack(alignment: .leading) {
                    Text(rec.map { jsonText($0["name"]) }.flatMap { $0.isEmpty ? nil : $0 } ?? layout.text("auto_location"))
                        .font(.system(size: 17, weight: .bold)).foregroundStyle(theme.text)
                    Text(layout.section("locations")?.title ?? "").font(.footnote).foregroundStyle(theme.muted)
                }
                Spacer()
                LoadBars(level: 5, color: theme.success, theme: theme)
            }
        }
    }

    @ViewBuilder private var locationsBody: some View {
        let nodes = data.nodes
        let busiest = max(nodes.map { jsonInt($0["users_online"]) ?? 0 }.max() ?? 1, 1)
        let rec = jsonText((data.routing["recommendation"] as? [String: Any])?["name"])
        if nodes.isEmpty { Text(layout.text("offline")).foregroundStyle(theme.muted) }
        ForEach(Array(nodes.enumerated()), id: \.offset) { _, node in
            let online = jsonText(node["status"]) == "online"
            let load = jsonInt(node["users_online"]) ?? 0
            CardView(theme: theme) {
                HStack(spacing: 14) {
                    Text(flagEmoji(jsonText(node["country"]))).font(.system(size: 28))
                    VStack(alignment: .leading) {
                        Text(jsonText(node["name"])).font(.system(size: 16, weight: .bold)).foregroundStyle(theme.text)
                        if jsonText(node["name"]) == rec { Text(layout.text("auto_location")).font(.caption).foregroundStyle(theme.accent) }
                    }
                    Spacer()
                    LoadBars(level: online ? min(max(5 - load * 4 / busiest, 1), 5) : 0, color: online ? theme.success : theme.danger, theme: theme)
                }
            }
        }
    }

    private var planId: Int { selectedPlan > 0 ? selectedPlan : (data.plans.first.flatMap { jsonInt($0["id"]) } ?? 0) }

    @ViewBuilder private var premiumBody: some View {
        let base = data.plans.min { (jsonInt($0["duration_days"]) ?? 30) < (jsonInt($1["duration_days"]) ?? 30) }.map(monthlyPrice) ?? 0
        ForEach(Array(data.plans.enumerated()), id: \.offset) { _, plan in
            let id = jsonInt(plan["id"]) ?? 0
            let chosen = id == planId
            let perMonth = monthlyPrice(plan)
            let discount = base > 0 && perMonth < base ? Int((1 - perMonth / base) * 100) : 0
            let price = (jsonText(plan["final_price"]).isEmpty ? jsonText(plan["price"]) : jsonText(plan["final_price"])).replacingOccurrences(of: ".00", with: "")
            Button { selectedPlan = id; track("plan_select") } label: {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(jsonText(plan["name"])).font(.system(size: 18, weight: .bold)).foregroundStyle(theme.text)
                        let devices = jsonInt(plan["device_limit"]) ?? 0
                        let gb = jsonInt(plan["traffic_limit_gb"]) ?? 0
                        Text([devices > 0 ? "\(layout.text("devices")): \(devices)" : nil, gb > 0 ? "\(gb) GB" : layout.text("unlimited")].compactMap { $0 }.joined(separator: " · "))
                            .font(.footnote).foregroundStyle(theme.muted)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("\(price) ₽").font(.system(size: 18, weight: .bold)).foregroundStyle(theme.accent2)
                        Text(String(format: "%.0f %@", perMonth, layout.text("per_month")) + (discount > 0 ? "  −\(discount)%" : "")).font(.footnote).foregroundStyle(theme.muted)
                    }
                    Image(systemName: chosen ? "checkmark.circle.fill" : "circle").foregroundStyle(chosen ? theme.accent2 : theme.muted).padding(.leading, 8)
                }
                .padding(18)
                .background(RoundedRectangle(cornerRadius: theme.radius).fill(theme.surface))
                .overlay(RoundedRectangle(cornerRadius: theme.radius).stroke(chosen ? theme.accent2 : .clear, lineWidth: 2))
            }
            .buttonStyle(.plain)
            .accessibilityAddTraits(chosen ? .isSelected : [])
        }
        Text(layout.text("consent")).font(.footnote).foregroundStyle(theme.muted)
    }

    @ViewBuilder private var subscriptionBody: some View {
        Button { copy(data.customerId) } label: {
            CardView(theme: theme) {
                HStack {
                    Text(layout.text("your_id")).fontWeight(.bold).foregroundStyle(theme.success)
                    Spacer()
                    Text(data.customerId.isEmpty ? "—" : data.customerId).fontWeight(.bold).foregroundStyle(theme.success)
                    Image(systemName: "doc.on.doc").foregroundStyle(theme.muted)
                }
            }
        }
        .buttonStyle(.plain)
        CardView(theme: theme) {
            Text(jsonText(data.subscription?["name"]).isEmpty ? layout.text("no_subscription") : jsonText(data.subscription?["name"]))
                .font(.system(size: 26, weight: .bold)).foregroundStyle(theme.text)
            if !untilLine.isEmpty { Text(untilLine).foregroundStyle(theme.muted) }
            infoLine(layout.text("devices"), "\(data.activeDevices) / \(jsonInt(data.currentPlan?["device_limit"]).flatMap { $0 > 0 ? String($0) : nil } ?? "∞")")
            infoLine(layout.text("traffic_left"), trafficLeft.0)
            infoLine(layout.text("servers"), "\(data.nodes.filter { jsonText($0["status"]) == "online" }.count)")
        }
        if data.profiles.count > 1 {
            ForEach(Array(data.profiles.enumerated()), id: \.offset) { _, profile in
                Button { selectProfile(profile) } label: {
                    CardView(theme: theme) {
                        HStack {
                            Text("\(jsonText(profile["name"])) · \(jsonText(profile["plan"]))").foregroundStyle(theme.text)
                            Spacer()
                            Image(systemName: jsonBool(profile["is_primary"]) ? "checkmark.circle.fill" : "circle").foregroundStyle(jsonBool(profile["is_primary"]) ? theme.accent : theme.muted)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func infoLine(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title).foregroundStyle(theme.muted)
            Spacer()
            Text(value).fontWeight(.bold).foregroundStyle(theme.text)
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.surface2))
    }

    @ViewBuilder private var devicesBody: some View {
        ForEach(Array(data.devices.enumerated()), id: \.offset) { _, device in
            CardView(theme: theme) {
                HStack {
                    VStack(alignment: .leading) {
                        Text(jsonText(device["name"])).fontWeight(.bold).foregroundStyle(theme.text)
                        Text("\(jsonText(device["platform"])) · \(jsonText(device["status"]))").font(.footnote).foregroundStyle(theme.muted)
                    }
                    Spacer()
                    if jsonText(device["status"]) == "active" {
                        Button { revokeDevice(device) } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(theme.danger) }.accessibilityLabel(t("revoke"))
                    }
                }
            }
        }
    }

    @ViewBuilder private var familySection: some View {
        let owned = data.family["owned"] as? [[String: Any]] ?? []
        let memberOf = data.family["member_of"] as? [[String: Any]] ?? []
        if owned.isEmpty && memberOf.isEmpty { Text(t("family_none")).foregroundStyle(theme.muted) }
        ForEach(Array(owned.enumerated()), id: \.offset) { _, group in
            CardView(theme: theme) {
                Text("\(t("family_owned")): \(jsonText(group["name"]))").fontWeight(.bold).foregroundStyle(theme.text)
                Text("\(t("family_seats")): \(jsonInt(group["used"]) ?? 0) / \(jsonInt(group["seats"]) ?? 0)").foregroundStyle(theme.muted)
                if let invite = group["invite"] as? [String: Any] {
                    Text(jsonText(invite["code"])).font(.title3.bold()).foregroundStyle(theme.accent2).textSelection(.enabled)
                }
                ForEach(Array((group["members"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { _, member in
                    HStack {
                        Text("\(jsonText(member["name"])) · \(jsonBool(member["synced"]) ? t("family_synced") : t("family_pending"))").foregroundStyle(theme.text)
                        Spacer()
                        Button(t("family_remove")) { familyAction("DELETE", "/api/me/family/members/\(jsonInt(member["id"]) ?? 0)") }.foregroundStyle(theme.danger).disabled(busy)
                    }
                }
            }
        }
        ForEach(Array(memberOf.enumerated()), id: \.offset) { _, row in
            CardView(theme: theme) {
                Text("\(t("family_member_of")) · \(t("family_owner")): \(jsonText(row["owner"]))").foregroundStyle(theme.text)
                Button(t("family_leave")) { familyAction("DELETE", "/api/me/family/members/\(jsonInt(row["id"]) ?? 0)") }.foregroundStyle(theme.danger).disabled(busy)
            }
        }
        InputField(title: t("family_code"), text: $familyCode, theme: theme)
        if !familyCode.trimmingCharacters(in: .whitespaces).isEmpty {
            ActionButtonView(button: LayoutButton(id: "join", label: t("family_join"), action: "open", target: "", style: "secondary", icon: "heart", audience: "any"), theme: theme, enabled: !busy) {
                familyAction("POST", "/api/me/family/join", body: ["code": familyCode.trimmingCharacters(in: .whitespaces)], done: t("family_joined"))
            }
        }
    }

    private var referralBody: some View {
        CardView(theme: theme) {
            Text(jsonText(data.user["referral_code"])).font(.system(size: 24, weight: .bold)).foregroundStyle(theme.accent2)
            let earned = jsonText(data.user["referral_balance"])
            if !earned.isEmpty && earned != "0" && earned != "0.00" { Text("+\(earned) ₽").foregroundStyle(theme.success) }
        }
    }

    @ViewBuilder private var walletBody: some View {
        CardView(theme: theme) {
            Text("\(jsonText(data.user["wallet_balance"]).isEmpty ? "0" : jsonText(data.user["wallet_balance"])) ₽").font(.system(size: 34, weight: .bold)).foregroundStyle(theme.text)
        }
        HStack(spacing: 8) {
            ForEach(["100", "300", "500", "1000"], id: \.self) { value in
                Button("\(value) ₽") { topupAmount = value }
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(value == topupAmount ? Color(hex: "#1A0F05") : theme.text)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(Capsule().fill(value == topupAmount ? theme.accent : theme.surface))
            }
        }
        InputField(title: "₽", text: $topupAmount, theme: theme).keyboardType(.numberPad)
    }

    @ViewBuilder private var notificationsBody: some View {
        ForEach(Array(data.notifications.enumerated()), id: \.offset) { _, n in
            Button { if !jsonBool(n["read"]) { markNotification(n) } } label: {
                CardView(theme: theme) {
                    HStack {
                        if !jsonBool(n["read"]) { Circle().fill(theme.accent).frame(width: 8, height: 8) }
                        Text(jsonText(n["title"])).fontWeight(.bold).foregroundStyle(theme.text)
                    }
                    Text(jsonText(n["body"])).font(.subheadline).foregroundStyle(theme.muted)
                }
            }
            .buttonStyle(.plain)
        }
    }

    @ViewBuilder private var statusSection: some View {
        let level = jsonText(data.status["status"])
        let srv = data.status["servers"] as? [String: Any] ?? [:]
        CardView(theme: theme) {
            HStack {
                Circle().fill(level == "ok" ? theme.success : level == "degraded" ? theme.accent2 : level == "down" ? theme.danger : theme.muted).frame(width: 12, height: 12)
                Text("\(layout.text("servers")): \(jsonInt(srv["online"]) ?? 0) / \(jsonInt(srv["total"]) ?? 0)").fontWeight(.bold).foregroundStyle(theme.text)
            }
        }
        ForEach(Array((data.status["countries"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { _, c in
            infoLine("\(flagEmoji(jsonText(c["country"])))  \(jsonText(c["country"]))", "\(jsonInt(c["online"]) ?? 0) / \(jsonInt(c["total"]) ?? 0)")
        }
        ForEach(Array((data.status["incidents"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { _, i in
            Text("\(jsonText(i["title"])) · \(jsonText(i["since"]))").foregroundStyle(theme.accent2)
        }
    }

    @ViewBuilder private var securityBody: some View {
        ForEach(Array(data.passkeys.enumerated()), id: \.offset) { _, key in
            CardView(theme: theme) {
                HStack {
                    Text(jsonText(key["name"])).foregroundStyle(theme.text)
                    Spacer()
                    Button { sheet = "passkey_delete:\(jsonInt(key["id"]) ?? 0)"; sheetText = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(theme.danger) }
                        .accessibilityLabel(t("passkey_delete"))
                }
            }
        }
    }

    // MARK: sheets

    @ViewBuilder private var sheetView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                switch sheet {
                case "qr":
                    Text(t("qr")).font(.title2.bold()).foregroundStyle(theme.text)
                    if let qr = data.qr {
                        Image(uiImage: qr).interpolation(.none).resizable().scaledToFit().padding(12)
                            .background(RoundedRectangle(cornerRadius: theme.radius).fill(Color.white))
                    }
                case "install":
                    Text(t("vpn_install")).font(.title2.bold()).foregroundStyle(theme.text)
                    Text(t("vpn_install_hint")).foregroundStyle(theme.muted)
                    ForEach(VpnClients.all.filter { !$0.store.isEmpty }, id: \.id) { client in
                        ActionButtonView(button: LayoutButton(id: client.id, label: client.title, action: "url", target: client.store, style: "secondary", icon: "download", audience: "any"), theme: theme) {
                            if let url = URL(string: client.store) { UIApplication.shared.open(url) }
                        }
                    }
                case "redeem":
                    Text(t("gift_code")).font(.title2.bold()).foregroundStyle(theme.text)
                    InputField(title: t("code"), text: $sheetText, theme: theme)
                    confirm(t("redeem"))
                case "ticket":
                    Text(t("support")).font(.title2.bold()).foregroundStyle(theme.text)
                    InputField(title: t("subject"), text: $sheetText2, theme: theme)
                    InputField(title: t("message"), text: $sheetText, theme: theme)
                    confirm(t("send"))
                case "report":
                    Text(t("report_subject")).font(.title2.bold()).foregroundStyle(theme.text)
                    Text(t("report_hint")).foregroundStyle(theme.muted)
                    InputField(title: t("message"), text: $sheetText, theme: theme)
                    confirm(t("send"))
                default:
                    Text(sheet == "passkey_add" ? t("passkey_add") : t("passkey_delete")).font(.title2.bold()).foregroundStyle(theme.text)
                    InputField(title: t("current_password"), text: $sheetText, theme: theme, secure: true)
                    confirm(t("done"))
                }
                ActionButtonView(button: LayoutButton(id: "close", label: ["qr", "install"].contains(sheet) ? t("done") : t("cancel"), action: "refresh", target: "", style: "ghost", icon: "", audience: "any"), theme: theme) { sheet = "" }
            }
            .padding(22)
        }
        .background(theme.background.ignoresSafeArea())
        .presentationDetents([.medium, .large])
    }

    private func confirm(_ title: String) -> some View {
        ActionButtonView(button: LayoutButton(id: "confirm", label: title, action: "refresh", target: "", style: "primary", icon: "", audience: "any"), theme: theme, enabled: !busy) { submitSheet() }
    }

    private func submitSheet() {
        let kind = sheet
        let text = sheetText.trimmingCharacters(in: .whitespacesAndNewlines)
        let text2 = sheetText2.trimmingCharacters(in: .whitespacesAndNewlines)
        sheet = ""
        switch kind {
        case "redeem":
            guard !text.isEmpty else { return }
            work {
                _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/gifts/redeem", body: ["code": text.uppercased()])
                DispatchQueue.main.async { notice = t("gift_ok"); refresh() }
            }
        case "ticket", "report":
            let subject = kind == "report" ? t("report_subject") : text2
            let message = kind == "report" ? "\(text)\n\n— \(appVersion) · iOS \(UIDevice.current.systemVersion) · VPN \(vpn)" : text
            guard !subject.isEmpty, !text.isEmpty else { return }
            work {
                _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/support/tickets", body: ["subject": subject, "message": message])
                DispatchQueue.main.async { notice = t("ticket_sent") }
            }
        case "passkey_add":
            let (api, session, language) = (base, token, lang)
            let deviceName = UIDevice.current.name  // UIKit is read on the main thread
            work {
                do {
                    try ShopPasskeys.register(base: api, session: session, lang: language, password: text, name: deviceName)
                } catch PasskeyError.cancelled {
                    DispatchQueue.main.async { notice = t("passkey_cancelled") }
                    return
                }
                DispatchQueue.main.async { notice = t("passkey_added"); refresh() }
            }
        default:
            guard kind.hasPrefix("passkey_delete:"), let id = Int(kind.dropFirst("passkey_delete:".count)) else { return }
            let (api, session, language) = (base, token, lang)
            work {
                try ShopPasskeys.delete(base: api, session: session, lang: language, id: id, password: text)
                DispatchQueue.main.async { notice = t("passkey_deleted"); refresh() }
            }
        }
    }

    // MARK: actions of the layout buttons

    private func run(_ button: LayoutButton) {
        switch button.action {
        case "connect", "auto_location":
            track("connect_tap")
            #if DEBUG
            if DemoMode.enabled { vpn = vpn == .on ? .off : .on; return }
            #endif
            if CorgiTunnelManager.available {
                // Embedded tunnel (Network Extension): no client app is needed.
                if vpn == .on || vpn == .connecting { CorgiTunnelManager.shared.disconnect(); vpn = .off; return }
                guard data.subscriptionUrl.hasPrefix("https://") else { notice = t("need_subscription"); return }
                vpn = .connecting; connectingSince = Date()
                CorgiTunnelManager.shared.connect(subscription: data.subscriptionUrl) { error in
                    if let error { vpn = .off; notice = error.localizedDescription }
                }
                return
            }
            switch VpnClients.connect(data.subscriptionUrl) {
            case .imported: vpn = .connecting; connectingSince = Date(); notice = t("vpn_imported")
            case .opened: notice = t("vpn_opened")
            case .noClient: sheet = "install"
            case .noSubscription:
                notice = t("need_subscription")
                if let premium = layout.sections.first(where: { $0.kind == "premium" }) { tab = premium.id }
            }
        case "open": if layout.section(button.target) != nil { tab = button.target; openDoc = nil; notice = "" }
        case "document": openDocument(button.target)
        case "url": openExternal(button.target)
        case "cabinet": openExternal(layout.links["cabinet"] ?? "")
        case "telegram_channel": openExternal(layout.links["telegram_channel"] ?? "")
        case "import_app":
            if data.subscriptionUrl.isEmpty { notice = t("need_subscription") }
            else if !VpnClients.importInto(button.target, data.subscriptionUrl) { sheet = "install" }
        case "copy_subscription": copy(data.subscriptionUrl)
        case "show_qr": sheet = "qr"
        case "copy_id": copy(data.customerId)
        case "buy": buy(wallet: false)
        case "pay_wallet": buy(wallet: true)
        case "trial": startTrial()
        case "topup": topUp()
        case "redeem": sheetText = ""; sheet = "redeem"
        case "share_referral": share(referralLink)
        case "copy_referral": copy(referralLink)
        case "family_invite": familyInvite()
        case "support_ticket": sheetText = ""; sheetText2 = ""; sheet = "ticket"
        case "report_problem": sheetText = ""; sheet = "report"
        case "language": lang = Self.nextLanguage(lang)
        case "push_toggle": if pushEnabled { disablePush() } else { enablePush() }
        case "passkey_add": sheetText = ""; sheet = "passkey_add"
        case "refresh": refresh()
        case "sign_out": signOut()
        default: break  // widget_toggle: the iOS app has no home screen widget yet
        }
    }

    private func prizeLine(_ row: [String: Any]) -> String {
        let best = (row["prizes"] as? [[String: Any]] ?? []).compactMap { Double(jsonText($0["amount"])) }.max() ?? 0
        let until = String(jsonText(row["ends_at"]).prefix(10))
        return [best > 0 ? "🏆 \(Int(best)) \(jsonText(row["currency"]))" : "", until.isEmpty ? "" : "\(layout.text("until")) \(until)"]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    @ViewBuilder private var giveawaysBody: some View {
        if data.giveaways.isEmpty { Text(layout.text("giveaway_none")).foregroundStyle(theme.muted) }
        ForEach(Array(data.giveaways.enumerated()), id: \.offset) { _, row in
            CardView(theme: theme) {
                Text(jsonText(row["title"])).font(.system(size: 17, weight: .bold)).foregroundStyle(theme.text)
                if !jsonText(row["description"]).isEmpty { Text(jsonText(row["description"])).font(.subheadline).foregroundStyle(theme.muted) }
                Text(prizeLine(row)).font(.footnote).foregroundStyle(theme.accent2)
                let mine = row["my_entry"] as? [String: Any]
                let outcome = jsonText(mine?["outcome"])
                if mine != nil && outcome == "won" {
                    Text(layout.text("giveaway_won").replacingOccurrences(of: "{amount}", with: "\(jsonText(mine?["reward_amount"])) \(jsonText(row["currency"]))"))
                        .bold().foregroundStyle(theme.success)
                } else if mine != nil && (outcome == "lost" || outcome == "ineligible") {
                    Text(layout.text("giveaway_lost")).foregroundStyle(theme.muted)
                } else if mine != nil {
                    Text(layout.text("giveaway_entered")).foregroundStyle(theme.muted)
                } else if jsonText(row["phase"]) == "open" {
                    ActionButtonView(button: LayoutButton(id: "giveaway_\(jsonInt(row["id"]) ?? 0)", label: layout.text("giveaway_join"), action: "refresh", target: "", style: "primary", icon: "trophy", audience: "any"), theme: theme, enabled: !busy) {
                        enterGiveaway(jsonInt(row["id"]) ?? 0)
                    }
                } else {
                    Text(layout.text("giveaway_closed")).foregroundStyle(theme.muted)
                }
            }
        }
    }

    private func enterGiveaway(_ id: Int) {
        guard id > 0 else { return }
        track("giveaway_enter")
        work {
            let row = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/giveaways/\(id)/enter") as? [String: Any] ?? [:]
            let mine = row["my_entry"] as? [String: Any]
            let won = jsonText(mine?["outcome"]) == "won"
            let text = won ? layout.text("giveaway_won").replacingOccurrences(of: "{amount}", with: "\(jsonText(mine?["reward_amount"])) \(jsonText(row["currency"]))") : layout.text("giveaway_entered")
            DispatchQueue.main.async { notice = text; refresh() }
        }
    }

    private func track(_ event: String, _ screen: String = "") {
        #if DEBUG
        if DemoMode.enabled { return }
        #endif
        CorgiAnalytics.track(base: base, token: token, event: event, screen: screen)
    }

    @ViewBuilder private var infoBody: some View {
        if data.docs.isEmpty { Text(layout.text("offline")).foregroundStyle(theme.muted) }
        ForEach(Array(data.docs.enumerated()), id: \.offset) { _, doc in
            Button { openDocument(jsonText(doc["kind"])) } label: {
                CardView(theme: theme) {
                    HStack {
                        Text(jsonText(doc["title"])).font(.system(size: 17, weight: .bold)).foregroundStyle(theme.text)
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(theme.muted)
                    }
                }
            }
            .buttonStyle(.plain)
        }
    }

    private func openDocument(_ kind: String) {
        guard ["faq", "rules", "privacy", "offer"].contains(kind) else { return }
        #if DEBUG
        if DemoMode.enabled {
            let title = layout.sections.flatMap(\.buttons).first { $0.action == "document" && $0.target == kind }?.label ?? kind
            openDoc = ["kind": kind, "title": title, "banner": "/api/bot/banners/default/app-info.jpg",
                       "body": "## Корги Люси\n- Один аккаунт — до пяти устройств\n- Возврат в течение **30 дней**\n\nВопросы — в поддержку."]
            return
        }
        #endif
        let (origin, session, language) = (base, token, lang)
        work {
            let page = try ShopClient(base: origin, token: session, lang: language).call("GET", "/api/public/info-pages/\(kind)?lang=\(language)") as? [String: Any]
            DispatchQueue.main.async { openDoc = page }
        }
    }

    private var referralLink: String {
        let code = jsonText(data.user["referral_code"])
        let bot = jsonText(data.config["bot_username"])
        return !bot.isEmpty && !code.isEmpty ? "https://t.me/\(bot)?start=ref_\(code)" : code
    }

    private func copy(_ value: String) {
        guard !value.isEmpty else { return }
        UIPasteboard.general.string = value
        notice = t("copied")
    }

    private func share(_ text: String) {
        guard !text.isEmpty, let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let root = scene.windows.first?.rootViewController else { return }
        root.present(UIActivityViewController(activityItems: [text], applicationActivities: nil), animated: true)
    }

    private func openExternal(_ raw: String) {
        guard !raw.contains(where: { $0.isWhitespace }), let target = URL(string: raw), target.user == nil, target.password == nil else { notice = t("link_missing"); return }
        let host = target.host?.lowercased() ?? ""
        let allowed = target.scheme == "https" || target.scheme == "tg" || (target.scheme == "http" && localHttpHosts.contains(host))
        if allowed { UIApplication.shared.open(target) } else { notice = t("link_missing") }
    }

    private func familyInvite() {
        guard let group = (data.family["owned"] as? [[String: Any]])?.first else { notice = t("family_none"); return }
        if let link = (group["invite"] as? [String: Any]).map({ jsonText($0["bot"]) }), !link.isEmpty { share(link); return }
        familyAction("POST", "/api/me/family/\(jsonInt(group["subscription_id"]) ?? 0)/invite")
    }

    private func familyAction(_ method: String, _ path: String, body: [String: Any]? = nil, done: String? = nil) {
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call(method, path, body: body)
            DispatchQueue.main.async {
                if let done { notice = done }
                familyCode = ""
                refresh()
            }
        }
    }

    private func authenticate(_ path: String) {
        guard let normalized = try? normalizeBase(base) else { notice = t("https_required"); return }
        guard email.contains("@"), email.contains(".") else { notice = t("email_invalid"); return }
        guard password.count >= 8 else { notice = t("password_short"); return }
        work {
            let response = try ShopClient(base: normalized, token: "", lang: lang).call("POST", path, body: ["email": email, "password": password]) as? [String: Any]
            let issued = response?["access_token"] as? String ?? ""
            guard !issued.isEmpty else { throw URLError(.userAuthenticationRequired) }
            try SessionKeychain.save(issued, base: normalized)
            DispatchQueue.main.async { base = normalized; token = issued; password = ""; unlocked = scenePhase == .active }
        }
    }

    private func loadMethods() {
        #if DEBUG
        if DemoMode.enabled { return }
        #endif
        guard let normalized = try? normalizeBase(base) else { return }
        let language = lang
        DispatchQueue.global(qos: .utility).async {
            guard let next = try? ShopClient(base: normalized, token: "", lang: language).call("GET", "/api/public/app-login/methods") as? [String: Any] else { return }
            DispatchQueue.main.async { methods = next }
        }
    }

    /// Redeems a one-use link from the bot, the cabinet or Yandex/VK/Google (POST /api/auth/mobile/code).
    private func redeem(_ link: LoginLink) {
        guard let origin = LoginLink.target(link, baked: bakedShopURL, current: (try? normalizeBase(base)) ?? "") else {
            notice = t("login_link_foreign"); return
        }
        work {
            let response = try ShopClient(base: origin, token: "", lang: lang).call("POST", "/api/auth/mobile/code", body: ["code": link.code]) as? [String: Any]
            let issued = response?["access_token"] as? String ?? ""
            guard !issued.isEmpty else { throw NSError(domain: "shop", code: 0, userInfo: [NSLocalizedDescriptionKey: t("login_link_invalid")]) }
            try SessionKeychain.save(issued, base: origin)
            DispatchQueue.main.async { base = origin; token = issued; password = ""; unlocked = scenePhase == .active }
        }
    }

    private func openOAuth(_ provider: String) {
        guard let origin = try? normalizeBase(base) else { notice = t("https_required"); return }
        // Safari comes back with corgi://login?code=… (app=1 in the OAuth state).
        openExternal("\(origin)/api/auth/\(provider)?app=1")
    }

    private func signInWithPasskey() {
        guard let normalized = try? normalizeBase(base) else { notice = t("https_required"); return }
        work {
            do {
                let issued = try ShopPasskeys.signIn(base: normalized, lang: lang)
                try SessionKeychain.save(issued, base: normalized)
                DispatchQueue.main.async { base = normalized; token = issued; password = ""; unlocked = scenePhase == .active }
            } catch PasskeyError.cancelled {
                DispatchQueue.main.async { notice = t("passkey_cancelled") }
            } catch PasskeyError.noPasskey {
                throw NSError(domain: "shop", code: 0, userInfo: [NSLocalizedDescriptionKey: t("passkey_none")])
            }
        }
    }

    private func loadLogo() {
        guard let normalized = try? normalizeBase(base) else { return }
        let language = lang
        DispatchQueue.global(qos: .utility).async {
            let api = ShopClient(base: normalized, token: "", lang: language)
            guard let catalog = try? api.call("GET", "/api/public/apps") as? [String: Any],
                  let media = catalog["logo_url"] as? String, let path = safeMediaPath(media),
                  let data = try? api.bytes(path), let image = UIImage(data: data) else { return }
            DispatchQueue.main.async { logo = image }
        }
    }

    private func loadLayout() {
        #if DEBUG
        if DemoMode.enabled { return }
        #endif
        guard let normalized = try? normalizeBase(base) else { return }
        let language = lang
        DispatchQueue.global(qos: .utility).async {
            PushCenter.registerCategories(base: normalized, lang: language)
            if let next = LayoutStore.fetch(base: normalized, lang: language) {
                DispatchQueue.main.async { if language == lang { layout = next; CorgiAnalytics.enabled = next.feature("analytics") } }
            }
        }
    }

    private func refresh() {
        #if DEBUG
        if DemoMode.enabled { return }  // screenshots: no network, fixed demo data
        #endif
        loadLayout()
        let (origin, session, language) = (base, token, lang)
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let api = ShopClient(base: origin, token: session, lang: language)
                var next = ShopData()
                next.dashboard = try api.call("GET", "/api/me/dashboard") as? [String: Any] ?? [:]
                next.profiles = try api.call("GET", "/api/me/subscriptions") as? [[String: Any]] ?? []
                next.plans = try api.call("GET", "/api/plans") as? [[String: Any]] ?? []
                next.servers = try api.call("GET", "/api/me/servers") as? [String: Any] ?? [:]
                next.connection = try api.call("GET", "/api/me/connection-info") as? [String: Any] ?? [:]
                next.config = try api.call("GET", "/api/public/config") as? [String: Any] ?? [:]
                next.traffic = try api.call("GET", "/api/me/traffic") as? [String: Any] ?? [:]
                next.devices = try api.call("GET", "/api/me/devices") as? [[String: Any]] ?? []
                next.notifications = try api.call("GET", "/api/me/mobile/notifications?unread_only=false") as? [[String: Any]] ?? []
                next.routing = try api.call("GET", "/api/me/routing/recommendation") as? [String: Any] ?? [:]
                next.qr = (try? api.bytes("/api/me/connection-qr")).flatMap(UIImage.init(data:))
                // Shops on releases before v28.25.0 have no family or status page: keep the rest working.
                next.family = (try? api.call("GET", "/api/me/family")) as? [String: Any] ?? [:]
                next.status = (try? api.call("GET", "/api/public/service-status")) as? [String: Any] ?? [:]
                next.passkeys = (try? ShopPasskeys.list(base: origin, session: session, lang: language)) ?? []
                // Shops before v28.29.0 have no documents: the section stays empty.
                next.docs = (try? api.call("GET", "/api/public/info-pages?lang=\(language)")) as? [[String: Any]] ?? []
                next.giveaways = ((try? api.call("GET", "/api/me/giveaways")) as? [String: Any])?["items"] as? [[String: Any]] ?? []
                // Re-bind a rotated APNs token, or the same token to a re-issued session.
                if PushCenter.shared.enabled, let current = PushCenter.shared.latestToken {
                    _ = try? PushCenter.register(base: origin, session: session, lang: language, token: current)
                }
                let loaded = next
                DispatchQueue.main.async { data = loaded; offline = false }
            } catch {
                DispatchQueue.main.async { offline = true; notice = error.localizedDescription }
            }
        }
    }

    private func markNotification(_ row: [String: Any]) {
        guard let id = jsonInt(row["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/mobile/notifications/\(id)/read")
            DispatchQueue.main.async { refresh() }
        }
    }

    private func signOut() {
        let previous = token
        let origin = base
        token = ""
        SessionKeychain.clear()
        unlocked = false
        pushEnabled = false
        data = ShopData()
        work {
            // Revoke the push token while the session is still valid, then end the session.
            PushCenter.unregister(base: origin, session: previous, lang: lang)
            if !previous.isEmpty {
                _ = try ShopClient(base: origin, token: previous, lang: lang).call("POST", "/api/auth/logout")
            }
        }
    }

    private func enablePush() {
        busy = true
        notice = ""
        push.requestToken { result in
            switch result {
            case .failure(let error):
                busy = false
                notice = (error as? PushError) == .denied ? t("push_denied") : error.localizedDescription
            case .success(let deviceToken):
                busy = false
                work {
                    let response = try PushCenter.register(base: base, session: token, lang: lang, token: deviceToken)
                    DispatchQueue.main.async {
                        pushEnabled = true
                        notice = jsonBool(response["push_available"]) ? t("push_on") : t("push_server_off")
                    }
                }
            }
        }
    }

    private func disablePush() {
        let session = token
        work {
            PushCenter.unregister(base: base, session: session, lang: lang)
            DispatchQueue.main.async { pushEnabled = false; notice = t("push_off") }
        }
    }

    private func unlockSavedSession() {
        authenticationContext?.invalidate()
        let context = LAContext()
        authenticationContext = context
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            unlocked = false
            notice = "Set a device passcode, or sign out and sign in again."
            return
        }
        context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: t("unlock")) { ok, _ in
            DispatchQueue.main.async {
                if ok && scenePhase == .active { unlocked = true; refresh() }
            }
        }
    }

    private func topUp() {
        let amount = topupAmount
        work {
            let response = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/wallet/topup", body: ["amount": amount, "provider": providerName()], idempotency: UUID().uuidString) as? [String: Any]
            DispatchQueue.main.async { notice = t("topup_ok"); openPayment(response?["url"] as? String ?? "") }
        }
    }

    private func revokeDevice(_ device: [String: Any]) {
        guard let id = jsonInt(device["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/devices/\(id)/revoke", body: [:])
            DispatchQueue.main.async { notice = t("device_revoked"); refresh() }
        }
    }

    private func selectProfile(_ profile: [String: Any]) {
        guard let id = jsonInt(profile["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/subscriptions/\(id)/select")
            DispatchQueue.main.async { refresh() }
        }
    }

    private func buy(wallet: Bool) {
        track("checkout_start")
        let id = planId
        work {
            let api = ShopClient(base: base, token: token, lang: lang)
            var body: [String: Any] = [:]
            if let sub = data.subscription, let selected = jsonInt(sub["id"]) { body["subscription_id"] = selected }
            if id > 0 {
                body["plan_id"] = id
            } else {
                // A shop that sells only through the tariff constructor: its first enabled options.
                guard let row = (try api.call("GET", "/api/tariff-constructors") as? [[String: Any]])?.first, let constructor = jsonInt(row["id"]) else { return }
                let options = row["options"] as? [[String: Any]] ?? []
                func pick(_ kind: String) -> Int { options.first { jsonText($0["kind"]) == kind }.flatMap { jsonInt($0["id"]) } ?? 0 }
                body["constructor_id"] = constructor
                body["device_option_id"] = pick("devices")
                body["traffic_option_id"] = pick("traffic_gb")
                body["days_option_id"] = pick("days")
            }
            if wallet {
                _ = try api.call("POST", "/api/me/wallet/spend", body: body, idempotency: UUID().uuidString)
                DispatchQueue.main.async { notice = t("paid_wallet"); refresh() }
            } else {
                body["provider"] = providerName()
                let response = try api.call("POST", "/api/payments/create", body: body, idempotency: UUID().uuidString) as? [String: Any]
                DispatchQueue.main.async {
                    notice = t("payment_created")
                    openPayment(response?["url"] as? String ?? "")
                }
            }
        }
    }

    private func startTrial() {
        track("trial_tap")
        let id = planId
        guard id > 0 else { return }
        let days = jsonInt(data.config["trial_days"]) ?? 3
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/trial", body: ["plan_id": id, "days": days])
            DispatchQueue.main.async { notice = t("trial_started"); refresh() }
        }
    }

    private func providerName() -> String {
        let providers = data.config["payment_providers"] as? [String] ?? []
        return providers.first { $0.lowercased() == "sandbox" } ?? providers.first ?? ""
    }

    private func openPayment(_ url: String) {
        guard !url.contains(where: { $0.isWhitespace }), let target = URL(string: url), target.user == nil, target.password == nil else { return }
        let host = target.host?.lowercased() ?? ""
        let allowed = target.scheme == "https" || (target.scheme == "http" && localHttpHosts.contains(host))
        if allowed { UIApplication.shared.open(target) }
    }

    private func work(_ block: @escaping () throws -> Void) {
        busy = true
        notice = ""
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try block()
                DispatchQueue.main.async { busy = false }
            } catch {
                DispatchQueue.main.async { busy = false; notice = error.localizedDescription }
            }
        }
    }
}

#if DEBUG
/// Screenshot mode for CI (Debug builds only): `-CorgiDemo -CorgiTab family` fills the screens
/// with fixed demo data and never touches the network or the keychain.
enum DemoMode {
    static var enabled: Bool { ProcessInfo.processInfo.arguments.contains("-CorgiDemo") }
    static var tab: String {
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-CorgiTab"), i + 1 < args.count else { return "vpn" }
        return args[i + 1] == "overview" ? "vpn" : args[i + 1]
    }
    static var vpnOn: Bool { ProcessInfo.processInfo.arguments.contains("-CorgiVpnOn") }
}

extension UserRootView {
    fileprivate func loadDemo() {
        let days: (Int) -> String = { ISO8601DateFormatter().string(from: Date().addingTimeInterval(Double($0) * 86400)) }
        base = ""
        token = "demo"
        unlocked = true
        tab = DemoMode.tab
        vpn = DemoMode.vpnOn ? .on : .off
        var demo = ShopData()
        demo.dashboard = ["user": ["id": 42, "wallet_balance": "350.00", "referral_code": "LUSI42", "referral_balance": "120.00"],
                          "subscription": ["id": 1, "name": "Премиум · 12 месяцев", "plan_id": 3, "status": "active", "expires_at": days(214)]]
        demo.profiles = [["id": 1, "name": "Основная", "plan": "Год", "expires_at": days(214), "is_primary": true]]
        demo.plans = [["id": 1, "name": "1 месяц", "price": "299.00", "duration_days": 30, "device_limit": 3],
                      ["id": 2, "name": "3 месяца", "price": "549.00", "duration_days": 90, "device_limit": 3],
                      ["id": 3, "name": "12 месяцев", "price": "1499.00", "duration_days": 365, "device_limit": 5]]
        demo.traffic = ["available": true, "traffic_used_bytes": 38_000_000_000, "traffic_limit_bytes": NSNull()]
        demo.servers = ["nodes": [["name": "Амстердам", "country": "NL", "status": "online", "users_online": 33],
                                  ["name": "Франкфурт", "country": "DE", "status": "online", "users_online": 41],
                                  ["name": "Хельсинки", "country": "FI", "status": "online", "users_online": 12],
                                  ["name": "Стокгольм", "country": "SE", "status": "online", "users_online": 8]]]
        demo.routing = ["recommendation": ["name": "Хельсинки", "country": "FI"]]
        demo.connection = ["subscription_url": "https://sub.example.com/s/demo"]
        demo.devices = [["id": 1, "name": "iPhone 16", "platform": "ios", "status": "active"], ["id": 2, "name": "MacBook", "platform": "macos", "status": "active"]]
        demo.family = ["owned": [["subscription_id": 1, "name": "Год", "seats": 3, "used": 2,
                                  "invite": ["code": "aB3x9Kq2", "bot": "https://t.me/corgi_lusi_bot?start=family_aB3x9Kq2"],
                                  "members": [["id": 1, "name": "mama", "synced": true]]]],
                       "member_of": []]
        demo.status = ["status": "ok", "servers": ["online": 5, "total": 5],
                       "countries": [["country": "DE", "online": 2, "total": 2], ["country": "NL", "online": 1, "total": 1], ["country": "FI", "online": 2, "total": 2]],
                       "components": [], "incidents": []]
        demo.notifications = [["id": 1, "title": "Подписка продлена", "body": "Спасибо! Следующее списание через 214 дней", "read": false]]
        demo.docs = [["kind": "faq", "title": "Частые вопросы"], ["kind": "rules", "title": "Правила"],
                     ["kind": "privacy", "title": "Политика конфиденциальности"], ["kind": "offer", "title": "Публичная оферта"]]
        demo.giveaways = [
            ["id": 7, "title": "Новогоднее колесо", "description": "Крутите колесо — до 1000 ₽ на баланс", "kind": "wheel", "phase": "open",
             "prizes": [["amount": "100", "weight": 5], ["amount": "1000", "weight": 1]], "currency": "RUB", "ends_at": "2026-12-31T21:00:00Z", "my_entry": NSNull()],
            ["id": 6, "title": "Розыгрыш года подписки", "description": "Три победителя получат год Премиума", "kind": "contest", "phase": "ended",
             "prizes": [["amount": "1499", "weight": 1]], "currency": "RUB", "ends_at": "2026-10-20T21:00:00Z", "my_entry": ["outcome": "won", "reward_amount": "1499.00"]],
        ]
        data = demo
    }
}
#endif
