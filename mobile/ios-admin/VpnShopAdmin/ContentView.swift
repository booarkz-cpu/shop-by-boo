import LocalAuthentication
import SwiftUI
import UIKit

struct AdminRootView: View {
    @AppStorage("shop_admin_lang") private var lang = "ru"
    @State private var activeId = ProfileVault.activeId()
    @State private var profiles = ProfileVault.all()
    @State private var base = ProfileVault.find(ProfileVault.activeId())?.base ?? ""
    @State private var token = ProfileVault.token(ProfileVault.activeId())
    @State private var profileLabel = ProfileVault.find(ProfileVault.activeId())?.label ?? ""
    @State private var showProfiles = false
    @State private var signedInIds: Set<String> = []
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.openURL) private var openURL
    @State private var authenticationContext: LAContext?
    @State private var email = ProfileVault.find(ProfileVault.activeId())?.email ?? ""
    @State private var password = ""
    @State private var otp = ""
    @State private var tab = "overview"
    @State private var notice = ""
    @State private var busy = false
    @State private var overview: [String: Any] = [:]
    @State private var plans: [[String: Any]] = []
    @State private var payments: [[String: Any]] = []
    @State private var monitoring: [String: Any] = [:]
    @State private var platform: [String: Any] = [:]
    @State private var tickets: [[String: Any]] = []
    @State private var broadcasts: [[String: Any]] = []
    @State private var broadcastText = ""
    @State private var broadcastTarget = "all"
    @State private var reply = ""
    @State private var unlocked = false
    @State private var paymentDetail: [String: Any] = [:]
    @State private var logo: UIImage?
    @State private var ops: [String: Any] = [:]
    @State private var nodeHealth: [String: Any] = [:]
    @State private var cashQueue: [[String: Any]] = []
    @State private var panels: [[String: Any]] = []
    @State private var pendingAction: [String: Any]?
    @State private var readiness: [String: Any] = [:]
    @State private var alerts: [String: Any] = [:]

    private func t(_ key: String) -> String { loadStrings(lang)[key] ?? key }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 12).fill(Remna.primary.opacity(0.14)).frame(width: 40, height: 40)
                        if let logo { Image(uiImage: logo).resizable().scaledToFit().frame(width: 30, height: 30) } else { Text("🐶").font(.title3) }
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t("app_name")).font(.system(size: 19, weight: .bold)).foregroundStyle(Remna.textStrong)
                        Text(!token.isEmpty && unlocked ? profileTitle() : t("tagline")).font(.footnote).foregroundStyle(Remna.muted).lineLimit(1)
                    }
                    Spacer()
                    RemnaGhost(title: lang == "ru" ? "EN" : "RU") { lang = lang == "ru" ? "en" : "ru" }
                }
                if !notice.isEmpty { RemnaNotice(text: notice) }
                if (token.isEmpty || unlocked) && !AdminDemo.enabled {
                    HStack {
                        Circle().fill(token.isEmpty ? Remna.muted : Remna.success).frame(width: 9, height: 9)
                        Text(base.isEmpty ? t("add_profile") : profileTitle()).foregroundStyle(Remna.primaryInk)
                        Spacer()
                        RemnaGhost(title: "\(t("profiles")) (\(profiles.count))") { reloadProfiles(); showProfiles.toggle() }
                    }
                }
                if showProfiles && (token.isEmpty || unlocked) { profilePanel }
                if token.isEmpty { auth } else if !unlocked { lock } else { home }
            }.padding(16)
        }
        .background(Remna.bg.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .overlay { if scenePhase != .active && !AdminDemo.enabled { Color.black.ignoresSafeArea() } }
        .onAppear {
            #if DEBUG
            if AdminDemo.enabled { loadDemo(); return }
            #endif
            if token.isEmpty { loadPublicLogo() }
            else if !unlocked { unlockSavedSession() }
        }
        .onChange(of: token) { value in
            if !value.isEmpty && unlocked && !AdminDemo.enabled { refresh() }
        }
        .onChange(of: scenePhase) { phase in
            if phase == .background && !AdminDemo.enabled {
                authenticationContext?.invalidate()
                authenticationContext = nil
                unlocked = false
            }
        }
        .onChange(of: unlocked) { value in if value && !token.isEmpty && !AdminDemo.enabled { refresh() } }
        .onChange(of: lang) { _ in if !token.isEmpty && unlocked && !AdminDemo.enabled { refresh() } }
    }

    #if DEBUG
    /// Fixed demo data for CI screenshots (-CorgiDemo -CorgiTab <tab>); nothing is requested.
    private func loadDemo() {
        func parse(_ text: String) -> Any { (try? JSONSerialization.jsonObject(with: Data(text.utf8))) ?? [:] }
        base = "https://api.corgi-lusi.example"; token = "demo"; unlocked = true; tab = AdminDemo.tab
        overview = parse(#"{"role":"admin","plans":4,"payments":1284,"users":5320,"active_subscriptions":2871,"revenue_today":"48 300","revenue_month":"1 214 900"}"#) as? [String: Any] ?? [:]
        plans = parse(#"[{"id":1,"name":"1 месяц","price":"299.00","enabled":true},{"id":2,"name":"3 месяца","price":"549.00","enabled":true},{"id":3,"name":"12 месяцев","price":"1499.00","enabled":true},{"id":4,"name":"Семейный","price":"2490.00","enabled":false}]"#) as? [[String: Any]] ?? []
        payments = parse(#"[{"id":1284,"amount":"1499.00","currency":"RUB","status":"fulfilled","provider":"yookassa"},{"id":1283,"amount":"299.00","currency":"RUB","status":"paid","provider":"platega"},{"id":1282,"amount":"549.00","currency":"RUB","status":"pending","provider":"rollypay"}]"#) as? [[String: Any]] ?? []
        monitoring = parse(#"{"nodes":[{"name":"Амстердам","country":"NL","status":"online","users_online":412},{"name":"Франкфурт","country":"DE","status":"online","users_online":388},{"name":"Стамбул","country":"TR","status":"offline","users_online":0}]}"#) as? [String: Any] ?? [:]
        platform = parse(#"{"violations":[{"id":17,"score":82,"recommendation":"Торрент-трафик: ограничить"}],"agents":[{"name":"nl-1","cpu":"23%"}],"countries":[{"country":"RU","count":4210},{"country":"KZ","count":512}]}"#) as? [String: Any] ?? [:]
        ops = parse(#"{"critical":0,"stale_agents":1,"agents":[{"name":"nl-1","cpu":"23%","mem":"41%"}]}"#) as? [String: Any] ?? [:]
        cashQueue = parse(#"[{"provider":"yookassa","enabled":true,"configured":true,"cooling":true,"success_count":1284,"failure_count":3},{"provider":"rollypay","enabled":true,"configured":true,"cooling":false,"success_count":212,"failure_count":0},{"provider":"freekassa","enabled":true,"configured":false,"cooling":false,"success_count":0,"failure_count":0}]"#) as? [[String: Any]] ?? []
        nodeHealth = parse(#"{"nodes":[{"uuid":"n1","name":"Нидерланды","status":"online","users_online":184,"down_minutes":0},{"uuid":"n2","name":"Германия","status":"offline","users_online":0,"down_minutes":4}]}"#) as? [String: Any] ?? [:]
        readiness = parse(#"{"ready":false,"checks":[{"title":"Платёжная система подключена","ok":true,"level":"required"},{"title":"Remnawave отвечает","ok":true,"level":"required"},{"title":"Чеки в налоговую","ok":false,"level":"recommended","hint":"Тарифы и оплата → Чеки в налоговую"}]}"#) as? [String: Any] ?? [:]
        alerts = parse(#"{"recipients":{"telegram":true,"email":false},"problems":[]}"#) as? [String: Any] ?? [:]
        tickets = parse(#"[{"id":311,"subject":"Не подключается на iPhone","status":"open","message":"После обновления iOS Happ не видит подписку."}]"#) as? [[String: Any]] ?? []
        broadcasts = parse(#"[{"id":42,"target":"active","status":"sent","sent_count":2871,"failed_count":3}]"#) as? [[String: Any]] ?? []
    }
    #endif

    private var profilePanel: some View {
        RemnaCard(title: t("profiles")) {
            ForEach(profiles) { profile in
                let current = profile.id == activeId
                let signed = signedInIds.contains(profile.id)
                RemnaRow(title: profile.title + (current ? " · \(t("active_profile"))" : ""), detail: profile.host + (profile.email.isEmpty ? "" : " · \(profile.email)"),
                         badge: signed ? t("signed_in") : t("signed_out"), tone: signed ? .ok : .muted) {
                    if !current { RemnaGhost(title: t("switch_profile")) { switchTo(profile.id) }.disabled(busy) }
                    RemnaGhost(title: t("remove_profile"), danger: true) { removeProfile(profile) }.disabled(busy)
                }
            }
            RemnaPrimary(title: t("add_profile")) { addProfile() }.disabled(busy)
        }
    }

    private func profileTitle() -> String { ProfileVault.find(activeId)?.title ?? (URL(string: base)?.host ?? base) }

    @ViewBuilder private var launchSection: some View {
        RemnaCard(title: t("launch")) {
            if readiness.isEmpty {
                RemnaEmpty(text: t("no_data"))
            } else {
                let ready = jsonBool(readiness["ready"])
                RemnaNotice(text: ready ? t("launch_ready") : t("launch_missing"), tone: ready ? .ok : .warn)
                ForEach(Array((readiness["checks"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { _, c in
                    let ok = jsonBool(c["ok"])
                    let required = jsonText(c["level"]) == "required"
                    RemnaRow(title: jsonText(c["title"]), detail: ok ? "" : jsonText(c["hint"]), badge: ok ? "✓" : required ? "✗" : t("recommended"),
                             tone: ok ? .ok : required ? .bad : .warn)
                }
            }
        }
        RemnaCard(title: t("alerts")) {
            let recipients = alerts["recipients"] as? [String: Any] ?? [:]
            let telegram = jsonBool(recipients["telegram"]), email = jsonBool(recipients["email"])
            RemnaRow(title: t("alerts_telegram"), badge: telegram ? t("configured") : t("not_configured"), tone: telegram ? .ok : .muted)
            RemnaRow(title: t("alerts_email"), badge: email ? t("configured") : t("not_configured"), tone: email ? .ok : .muted)
            RemnaPrimary(title: t("alerts_test")) {
                work {
                    _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/ops/alerts/test")
                    DispatchQueue.main.async { notice = t("alerts_sent") }
                }
            }.disabled(busy || !(telegram || email) || AdminDemo.enabled)
            Text(t("problems_now")).font(.subheadline.weight(.semibold)).foregroundStyle(Remna.textStrong)
            let problems = alerts["problems"] as? [[String: Any]] ?? []
            if problems.isEmpty { RemnaEmpty(text: t("no_problems")) }
            ForEach(Array(problems.enumerated()), id: \.offset) { _, p in
                RemnaRow(title: jsonText(p["title"]), detail: jsonText(p["detail"]), badge: "!", tone: .warn)
            }
        }
    }

    private func clearLoaded() {
        overview = [:]; plans = []; payments = []; monitoring = [:]; platform = [:]; ops = [:]; nodeHealth = [:]; cashQueue = []; panels = []; readiness = [:]; alerts = [:]
        tickets = []; broadcasts = []; paymentDetail = [:]; logo = nil; reply = ""; broadcastText = ""
    }

    private func reloadProfiles() {
        profiles = ProfileVault.all()
        signedInIds = Set(profiles.filter { !ProfileVault.token($0.id).isEmpty }.map(\.id))
    }

    private func switchTo(_ id: String) {
        clearLoaded()
        ProfileVault.setActive(id)
        activeId = id
        let profile = ProfileVault.find(id)
        base = profile?.base ?? ""
        email = profile?.email ?? ""
        profileLabel = profile?.label ?? ""
        password = ""; otp = ""; tab = "overview"
        showProfiles = false
        token = ProfileVault.token(id)
        notice = profile.map { t("profile_switched").replacingOccurrences(of: "{profile}", with: $0.title) } ?? ""
    }

    private func addProfile() {
        guard profiles.count < ProfileVault.maxProfiles else { notice = t("profile_limit"); return }
        clearLoaded()
        activeId = ProfileVault.newId()
        base = ""; email = ""; password = ""; otp = ""; profileLabel = ""; token = ""
        showProfiles = false
        notice = ""
    }

    private func removeProfile(_ profile: AdminProfile) {
        let removedToken = ProfileVault.token(profile.id)
        ProfileVault.remove(profile.id)
        if !removedToken.isEmpty {
            DispatchQueue.global(qos: .utility).async {
                _ = try? ShopClient(base: profile.base, token: removedToken, lang: lang).call("POST", "/api/admin/auth/logout")
            }
        }
        reloadProfiles()
        if profile.id == activeId {
            if let next = profiles.first { switchTo(next.id) } else { addProfile() }
        }
        notice = t("profile_removed")
    }

    private var auth: some View {
        RemnaCard(title: t("sign_in"), hint: t("tagline")) {
            RemnaField(title: t("profile_label"), text: $profileLabel)
            RemnaField(title: t("server"), text: $base)
            RemnaField(title: t("email"), text: $email)
            RemnaField(title: t("password"), text: $password, secure: true)
            RemnaField(title: t("otp"), text: $otp)
            RemnaPrimary(title: t("sign_in")) { signIn() }.disabled(busy)
        }
    }

    private var lock: some View {
        RemnaCard(title: t("unlock")) {
            RemnaPrimary(title: t("unlock")) { unlockSavedSession() }
            RemnaGhost(title: t("sign_out"), danger: true) { signOut() }
        }
    }

    private var home: some View {
        VStack(alignment: .leading, spacing: 12) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(["overview", "launch", "plans", "payments", "monitoring", "platform", "ops", "support", "broadcast", "panel"], id: \.self) { key in
                        RemnaPill(title: t(key), selected: tab == key) { tab = key }
                    }
                }
            }
            HStack(spacing: 8) {
                RemnaGhost(title: t("refresh")) { refresh() }.disabled(busy || AdminDemo.enabled)
                RemnaGhost(title: t("sign_out"), danger: true) { signOut() }
            }
            section
        }
    }

    private func money(_ value: Any?) -> String { jsonText(value).replacingOccurrences(of: ".00", with: "") }

    @ViewBuilder private var section: some View {
        switch tab {
        case "overview":
            HStack(spacing: 10) {
                RemnaKpi(label: t("plans"), value: "\(jsonInt(overview["plans"]) ?? 0)")
                RemnaKpi(label: t("payments"), value: "\(jsonInt(overview["payments"]) ?? 0)")
            }
            if overview["users"] != nil {
                HStack(spacing: 10) {
                    RemnaKpi(label: "Клиенты", value: jsonText(overview["users"]))
                    RemnaKpi(label: "Активные подписки", value: jsonText(overview["active_subscriptions"]))
                }
            }
            if overview["revenue_today"] != nil {
                HStack(spacing: 10) {
                    RemnaKpi(label: "Выручка сегодня, ₽", value: jsonText(overview["revenue_today"]))
                    RemnaKpi(label: "За месяц, ₽", value: jsonText(overview["revenue_month"]))
                }
            }
            RemnaCard(title: t("role")) { RemnaRow(title: overview["role"] as? String ?? "—", detail: profileTitle(), badge: t("online"), tone: .ok) }
        case "plans":
            RemnaCard(title: t("plans")) {
                if plans.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(plans.enumerated()), id: \.offset) { _, plan in
                    let on = jsonBool(plan["enabled"])
                    RemnaRow(title: jsonText(plan["name"]), detail: "\(money(plan["price"])) ₽", badge: on ? t("enabled") : t("disabled"), tone: on ? .ok : .muted) {
                        RemnaGhost(title: on ? t("disable_plan") : t("enable_plan")) { setPlan(plan, enabled: !on) }.disabled(AdminDemo.enabled)
                    }
                }
            }
        case "payments":
            // The order of gateways: an order goes to the first enabled, configured one that is not cooling down.
            RemnaCard(title: t("cash_queue")) {
                if cashQueue.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(cashQueue.enumerated()), id: \.offset) { index, row in
                    let enabled = (row["enabled"] as? Bool) ?? false
                    let cooling = (row["cooling"] as? Bool) ?? false
                    let configured = (row["configured"] as? Bool) ?? false
                    let state = !enabled ? t("disabled") : cooling ? t("cash_cooling") : configured ? t("cash_ready") : t("cash_no_keys")
                    RemnaRow(title: "\(index + 1). \(jsonText(row["provider"]))", detail: "\(jsonText(row["success_count"])) / \(jsonText(row["failure_count"]))", badge: state) {
                        RemnaGhost(title: enabled ? t("cash_off") : t("cash_on")) { setCash(index, enabled: !enabled) }.disabled(busy || AdminDemo.enabled)
                        if index > 0 { RemnaGhost(title: t("cash_up")) { moveCashUp(index) }.disabled(busy || AdminDemo.enabled) }
                        if cooling { RemnaPrimary(title: t("cash_reset")) { resetCash(row) }.disabled(busy || AdminDemo.enabled) }
                    }
                }
            }
            RemnaCard(title: t("payments")) {
                if payments.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(payments.enumerated()), id: \.offset) { _, payment in
                    RemnaRow(title: "#\(jsonText(payment["id"])) · \(money(payment["amount"])) \(jsonText(payment["currency"]))", detail: jsonText(payment["provider"]),
                             badge: jsonText(payment["status"])) {
                        RemnaGhost(title: t("payment_detail")) { loadPayment(payment) }.disabled(AdminDemo.enabled)
                    }
                }
                if !paymentDetail.isEmpty {
                    RemnaNotice(text: "#\(jsonText(paymentDetail["id"])) · \(jsonText(paymentDetail["order_id"])) · \(jsonText(paymentDetail["purpose"])) · \(jsonText(paymentDetail["fulfillment_status"]))", tone: .info)
                }
            }
        case "monitoring":
            RemnaCard(title: t("monitoring")) {
                if (monitoring["error"] as? String)?.isEmpty == false { RemnaNotice(text: t("panel_down"), tone: .bad) }
                let nodes = monitoring["nodes"] as? [[String: Any]] ?? []
                if nodes.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(nodes.enumerated()), id: \.offset) { _, row in
                    let node = publicNode(row)
                    RemnaRow(title: jsonText(node["name"]), detail: "\(jsonText(node["country"])) · \(jsonInt(node["users_online"]) ?? 0) online", badge: jsonText(node["status"]))
                }
            }
        case "platform":
            RemnaCard(title: t("violations")) {
                let violations = platform["violations"] as? [[String: Any]] ?? []
                if violations.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(violations.enumerated()), id: \.offset) { _, row in
                    let score = jsonInt(row["score"]) ?? 0
                    RemnaRow(title: "#\(jsonText(row["id"])) · \(t("score")) \(score)", detail: jsonText(row["recommendation"]), badge: "\(score)", tone: score >= 70 ? .bad : .warn) {
                        RemnaGhost(title: t("restrict"), danger: true) { review(row, "restrict") }.disabled(AdminDemo.enabled)
                        RemnaGhost(title: t("clear")) { review(row, "clear") }.disabled(AdminDemo.enabled)
                    }
                }
            }
            RemnaCard(title: t("agents")) {
                ForEach(Array((platform["agents"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { _, agent in
                    let stale = jsonBool(agent["stale"])
                    RemnaRow(title: jsonText(agent["name"]), detail: "CPU \(jsonText(agent["cpu"]))", badge: stale ? t("stale") : t("online"), tone: stale ? .warn : .ok)
                }
            }
            RemnaCard(title: t("countries")) {
                ForEach(Array((platform["countries"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { _, country in
                    RemnaRow(title: jsonText(country["country"]), badge: jsonText(country["count"]), tone: .info)
                }
            }
        case "launch":
            launchSection
        case "ops":
            HStack(spacing: 10) {
                RemnaKpi(label: t("critical"), value: jsonText(ops["critical"]).isEmpty ? "0" : jsonText(ops["critical"]))
                RemnaKpi(label: t("stale_agents"), value: jsonText(ops["stale_agents"]).isEmpty ? "0" : jsonText(ops["stale_agents"]))
            }
            RemnaCard(title: t("ops")) {
                let agents = ops["agents"] as? [[String: Any]] ?? []
                if agents.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(agents.enumerated()), id: \.offset) { _, agent in
                    RemnaRow(title: jsonText(agent["name"]), detail: "CPU \(jsonText(agent["cpu"])) · RAM \(jsonText(agent["mem"]))", badge: t("online"), tone: .ok)
                }
            }
            RemnaCard(title: t("nodes")) {
                let nodes = nodeHealth["nodes"] as? [[String: Any]] ?? []
                if let error = nodeHealth["error"] as? String, !error.isEmpty { RemnaEmpty(text: error) }
                if nodes.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(nodes.enumerated()), id: \.offset) { _, node in
                    let status = jsonText(node["status"])
                    let detail = status == "online" ? "\(jsonText(node["users_online"])) online" : "\(t("node_down")) \(jsonText(node["down_minutes"])) мин"
                    RemnaRow(title: jsonText(node["name"]), detail: detail, badge: status) {
                        RemnaGhost(title: t("node_restart")) { restartNode(node) }.disabled(busy || AdminDemo.enabled)
                    }
                }
            }
            // Module panels (mobile_panels.py): rows and actions described by the shop itself.
            ForEach(Array(panels.enumerated()), id: \.offset) { _, panel in
                RemnaCard(title: jsonText(panel["title"])) {
                    let rows = panel["rows"] as? [[String: Any]] ?? []
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, line in
                        let tone: RemnaTone? = ["ok": .ok, "warn": .warn, "bad": .bad][jsonText(line["tone"])]
                        RemnaRow(title: jsonText(line["label"]), detail: jsonText(line["value"]), tone: tone)
                    }
                    let actions = panel["actions"] as? [[String: Any]] ?? []
                    ForEach(Array(actions.enumerated()), id: \.offset) { _, act in
                        RemnaGhost(title: jsonText(act["label"])) {
                            if jsonText(act["confirm"]).isEmpty { runPanelAction(act) } else { pendingAction = act }
                        }.disabled(busy || AdminDemo.enabled)
                    }
                }
            }
            .alert(jsonText(pendingAction?["confirm"]), isPresented: Binding(get: { pendingAction != nil }, set: { if !$0 { pendingAction = nil } })) {
                Button(jsonText(pendingAction?["label"])) { if let act = pendingAction { runPanelAction(act) }; pendingAction = nil }
                Button(t("panel_cancel"), role: .cancel) { pendingAction = nil }
            }
        case "panel":
            // Everything the native tabs do not cover lives in the web panel; the ticket is single-use and lives 60 s.
            RemnaCard(title: t("panel"), hint: t("panel_hint")) {
                RemnaPrimary(title: t("panel_open")) { openFullPanel() }.disabled(busy || AdminDemo.enabled)
            }
        case "broadcast":
            RemnaCard(title: t("broadcast"), hint: t("broadcast_hint")) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        RemnaPill(title: t("all_telegram"), selected: broadcastTarget == "all") { broadcastTarget = "all" }
                        RemnaPill(title: t("active_subs"), selected: broadcastTarget == "active") { broadcastTarget = "active" }
                        RemnaPill(title: t("inactive_subs"), selected: broadcastTarget == "inactive") { broadcastTarget = "inactive" }
                    }
                }
                RemnaField(title: t("broadcast_text"), text: $broadcastText)
                RemnaPrimary(title: t("queue_broadcast")) { queueBroadcast() }.disabled(busy || AdminDemo.enabled)
            }
            RemnaCard(title: t("sent")) {
                if broadcasts.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(broadcasts.enumerated()), id: \.offset) { _, row in
                    let audience = (row["target"] as? String) == "active" ? t("active_subs") : (row["target"] as? String) == "inactive" ? t("inactive_subs") : t("all_telegram")
                    let status = jsonText(row["status"])
                    RemnaRow(title: "#\(jsonText(row["id"])) · \(audience)", detail: "\(t("sent")) \(jsonText(row["sent_count"])) · \(t("failed")) \(jsonText(row["failed_count"]))", badge: status) {
                        if status == "sending" || status == "failed" { RemnaGhost(title: t("retry_broadcast")) { retryBroadcast(row) }.disabled(busy) }
                    }
                }
            }
        default:
            RemnaCard(title: t("support")) {
                RemnaField(title: t("reply"), text: $reply)
                if tickets.isEmpty { RemnaEmpty(text: t("no_data")) }
                ForEach(Array(tickets.enumerated()), id: \.offset) { _, ticket in
                    RemnaRow(title: "#\(jsonText(ticket["id"])) · \(jsonText(ticket["subject"]))", detail: jsonText(ticket["message"]), badge: jsonText(ticket["status"])) {
                        RemnaGhost(title: t("ai_draft")) { aiDraft(ticket) }.disabled(busy || AdminDemo.enabled)
                        RemnaPrimary(title: t("send")) { send(ticket) }.disabled(busy || AdminDemo.enabled)
                    }
                }
            }
        }
    }

    private func signIn() {
        guard let normalized = try? normalizeBase(base) else { notice = t("https_required"); return }
        guard email.contains("@"), email.contains(".") else { notice = t("email_invalid"); return }
        guard password.count >= 8 else { notice = t("password_short"); return }
        let profileId = activeId
        let address = email.trimmingCharacters(in: .whitespaces)
        if ProfileVault.duplicate(of: profileId, base: normalized, email: address) != nil {
            notice = t("profile_duplicate"); reloadProfiles(); showProfiles = true; return
        }
        if ProfileVault.find(profileId) == nil && ProfileVault.all().count >= ProfileVault.maxProfiles { notice = t("profile_limit"); return }
        let label = String(profileLabel.trimmingCharacters(in: .whitespaces).prefix(40))
        work {
            var body: [String: Any] = ["email": address, "password": password]
            if !otp.trimmingCharacters(in: .whitespaces).isEmpty { body["otp"] = otp }
            let response = try ShopClient(base: normalized, token: "", lang: lang).call("POST", "/api/admin/auth/login", body: body) as? [String: Any]
            let issued = response?["access_token"] as? String ?? ""
            guard !issued.isEmpty else { throw URLError(.userAuthenticationRequired) }
            try SessionKeychain.save(issued, base: normalized, account: ProfileVault.account(profileId))
            ProfileVault.upsert(AdminProfile(id: profileId, label: label, base: normalized, email: address))
            ProfileVault.setActive(profileId)
            DispatchQueue.main.async {
                reloadProfiles()
                base = normalized
                token = issued
                password = ""
                otp = ""
                unlocked = scenePhase == .active
                notice = "\(t("role")): \(response?["role"] as? String ?? "")"
            }
        }
    }

    private func logoImage(_ api: ShopClient, _ path: String) -> UIImage? {
        guard let catalog = try? api.call("GET", path) as? [String: Any],
              let media = catalog["logo_url"] as? String,
              let data = try? api.bytes(media) else { return nil }
        return UIImage(data: data)
    }

    private func loadPublicLogo() {
        guard let normalized = try? normalizeBase(base) else { return }
        work {
            let image = logoImage(ShopClient(base: normalized, token: "", lang: lang), "/api/public/apps")
            DispatchQueue.main.async { logo = image }
        }
    }

    private func runPanelAction(_ act: [String: Any]) {
        let method = jsonText(act["method"]), path = jsonText(act["path"])
        // Only admin API paths; the shop checks the permission of every action as in the web admin.
        guard path.hasPrefix("/api/admin/"), ["POST", "PUT", "DELETE"].contains(method) else { return }
        let body = act["body"] as? [String: Any] ?? [:]
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call(method, path, body: method == "DELETE" ? nil : body)
            DispatchQueue.main.async { notice = t("panel_done"); refresh() }
        }
    }

    private func refresh() {
        let refreshedFor = activeId
        work {
            let api = ShopClient(base: base, token: token, lang: lang)
            let nextOverview = try api.call("GET", "/api/admin/overview") as? [String: Any] ?? [:]
            let nextPlans = try api.call("GET", "/api/admin/plans") as? [[String: Any]] ?? []
            let nextPayments = try api.call("GET", "/api/admin/payments") as? [[String: Any]] ?? []
            let nextMonitoring = try api.call("GET", "/api/admin/remnawave/monitoring") as? [String: Any] ?? [:]
            let nextPlatform = try api.call("GET", "/api/admin/platform/summary") as? [String: Any] ?? [:]
            let nextOps = try api.call("GET", "/api/admin/mobile/ops") as? [String: Any] ?? [:]
            let nextTickets = try api.call("GET", "/api/admin/support/tickets") as? [[String: Any]] ?? []
            // Shops before v28.27.0 have no launch checks: the other tabs keep working.
            let nextReadiness = (try? api.call("GET", "/api/admin/ops/readiness")) as? [String: Any] ?? [:]
            let nextAlerts = (try? api.call("GET", "/api/admin/ops/alerts")) as? [String: Any] ?? [:]
            // Node health appeared in v28.35: older shops simply show no node card.
            let nextNodeHealth = (try? api.call("GET", "/api/admin/nodes/health")) as? [String: Any] ?? [:]
            let nextCash = (try? api.call("GET", "/api/admin/v41/providers")) as? [[String: Any]] ?? []
            // Module panels appeared in v28.37: older shops simply show none.
            let nextPanels = ((try? api.call("GET", "/api/admin/mobile/panels")) as? [String: Any])?["panels"] as? [[String: Any]] ?? []
            let nextMarketing = try api.call("GET", "/api/admin/marketing") as? [String: Any] ?? [:]
            let nextBroadcasts = nextMarketing["broadcasts"] as? [[String: Any]] ?? []
            let nextLogo = logoImage(api, "/api/admin/apps")
            DispatchQueue.main.async {
                // A slow response must not paint the previous profile's data after a switch.
                guard refreshedFor == activeId else { return }
                overview = nextOverview
                plans = nextPlans
                payments = nextPayments
                monitoring = nextMonitoring
                platform = nextPlatform
                ops = nextOps
                nodeHealth = nextNodeHealth
                cashQueue = nextCash
                panels = nextPanels
                readiness = nextReadiness
                alerts = nextAlerts
                tickets = nextTickets
                broadcasts = nextBroadcasts
                logo = nextLogo
            }
        }
    }

    private func signOut() {
        let previous = token
        let origin = base
        token = ""
        SessionKeychain.clear(account: ProfileVault.account(activeId))
        unlocked = false
        clearLoaded()
        work {
            if !previous.isEmpty {
                _ = try ShopClient(base: origin, token: previous, lang: lang).call("POST", "/api/admin/auth/logout")
            }
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

    private func putCash(_ row: [String: Any], enabled: Bool, priority: Int) throws {
        let name = jsonText(row["provider"])
        _ = try ShopClient(base: base, token: token, lang: lang).call("PUT", "/api/admin/v41/providers/\(name)", body: ["enabled": enabled, "priority": priority])
    }

    private func setCash(_ index: Int, enabled: Bool) {
        let row = cashQueue[index]
        work {
            try putCash(row, enabled: enabled, priority: (index + 1) * 10)
            DispatchQueue.main.async { notice = t("cash_saved"); refresh() }
        }
    }

    private func moveCashUp(_ index: Int) {
        let row = cashQueue[index], above = cashQueue[index - 1]
        work {
            try putCash(row, enabled: (row["enabled"] as? Bool) ?? false, priority: index * 10)
            try putCash(above, enabled: (above["enabled"] as? Bool) ?? false, priority: (index + 1) * 10)
            DispatchQueue.main.async { notice = t("cash_saved"); refresh() }
        }
    }

    private func resetCash(_ row: [String: Any]) {
        let name = jsonText(row["provider"])
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/v41/providers/\(name)/reset")
            DispatchQueue.main.async { refresh() }
        }
    }

    private func setPlan(_ plan: [String: Any], enabled: Bool) {
        guard let id = jsonInt(plan["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/plans/\(id)/enabled", body: ["enabled": enabled])
            DispatchQueue.main.async { notice = t("plan_saved") }
        }
    }

    private func loadPayment(_ payment: [String: Any]) {
        guard let id = jsonInt(payment["id"]) else { return }
        work {
            let detail = try ShopClient(base: base, token: token, lang: lang).call("GET", "/api/admin/payments/\(id)") as? [String: Any] ?? [:]
            DispatchQueue.main.async { paymentDetail = detail }
        }
    }

    private func review(_ row: [String: Any], _ action: String) {
        guard let id = jsonInt(row["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/platform/violations/\(id)/review", body: ["action": action])
            DispatchQueue.main.async { notice = t(action == "restrict" ? "restricted" : "cleared") }
        }
    }

    private func queueBroadcast() {
        let text = broadcastText.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return }
        let target = broadcastTarget
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/broadcasts", body: ["text": text, "target": target])
            DispatchQueue.main.async { notice = t("broadcast_queued"); broadcastText = "" }
        }
    }

    private func retryBroadcast(_ row: [String: Any]) {
        guard let id = jsonInt(row["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/broadcasts/\(id)/retry")
            DispatchQueue.main.async { notice = t("broadcast_retried") }
        }
    }

    private func send(_ ticket: [String: Any]) {
        guard let id = jsonInt(ticket["id"]) else { return }
        let text = reply.trimmingCharacters(in: .whitespaces)
        if text.isEmpty { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/support/tickets/\(id)/reply", body: ["reply": text])
            DispatchQueue.main.async { notice = t("reply_sent"); reply = "" }
        }
    }

    private func aiDraft(_ ticket: [String: Any]) {
        guard let id = jsonInt(ticket["id"]) else { return }
        work {
            let out = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/support/tickets/\(id)/draft") as? [String: Any] ?? [:]
            DispatchQueue.main.async { reply = jsonText(out["draft"]) }
        }
    }

    private func restartNode(_ node: [String: Any]) {
        let uuid = jsonText(node["uuid"])
        if uuid.isEmpty { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/nodes/\(uuid)/restart")
            DispatchQueue.main.async { notice = t("node_restarted") }
        }
    }

    private func openFullPanel() {
        work {
            let out = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/admin/auth/web-ticket") as? [String: Any] ?? [:]
            guard let raw = out["url"] as? String, raw.hasPrefix("https://"), let url = URL(string: raw) else { return }
            DispatchQueue.main.async { openURL(url) }
        }
    }

    private func work(_ block: @escaping () throws -> Void) {
        busy = true
        notice = ""
        let startedFor = activeId
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try block()
                DispatchQueue.main.async { busy = false }
            } catch {
                let failure = error as NSError
                DispatchQueue.main.async {
                    busy = false
                    if failure.domain == "shop" && failure.code == 401 {
                        notice = t("session_expired").replacingOccurrences(of: "{profile}", with: profileTitle())
                        // Keep the profile, drop only its dead session, so the admin can sign in again.
                        if startedFor == activeId {
                            SessionKeychain.clear(account: ProfileVault.account(activeId))
                            token = ""
                            clearLoaded()
                        }
                    } else if failure.domain == "shop" && failure.code == 403 {
                        let detail = failure.localizedDescription
                        notice = detail.hasPrefix("HTTP") ? t("forbidden") : detail
                    } else if failure.domain == NSURLErrorDomain {
                        notice = "\(t("network_error").replacingOccurrences(of: "{profile}", with: profileTitle())) (\(failure.code))"
                    } else {
                        notice = failure.localizedDescription
                    }
                }
            }
        }
    }
}

// MARK: - Remna Dark: the look of the web admin panel (admin/src/theme.css)

enum AdminDemo {
    static var enabled: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-CorgiDemo")
        #else
        return false
        #endif
    }
    static var tab: String {
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-CorgiTab"), i + 1 < args.count else { return "overview" }
        return args[i + 1]
    }
}

enum Remna {
    static let bg = Color(red: 0.035, green: 0.051, blue: 0.086)
    static let surface = Color(red: 0.059, green: 0.090, blue: 0.165)
    static let surface2 = Color(red: 0.075, green: 0.110, blue: 0.192)
    static let input = Color(red: 0.043, green: 0.071, blue: 0.125)
    static let line = Color(red: 0.118, green: 0.161, blue: 0.231)
    static let lineStrong = Color(red: 0.173, green: 0.231, blue: 0.341)
    static let text = Color(red: 0.886, green: 0.910, blue: 0.941)
    static let textStrong = Color(red: 0.973, green: 0.980, blue: 0.988)
    static let muted = Color(red: 0.580, green: 0.639, blue: 0.722)
    static let subtle = Color(red: 0.392, green: 0.455, blue: 0.545)
    static let primary = Color(red: 0.231, green: 0.510, blue: 0.965)
    static let primaryInk = Color(red: 0.576, green: 0.773, blue: 0.992)
    static let success = Color(red: 0.133, green: 0.773, blue: 0.369)
    static let warning = Color(red: 0.961, green: 0.620, blue: 0.043)
    static let danger = Color(red: 0.937, green: 0.267, blue: 0.267)
}

enum RemnaTone { case ok, warn, bad, info, muted
    var color: Color {
        switch self { case .ok: return Remna.success; case .warn: return Remna.warning; case .bad: return Remna.danger; case .info: return Remna.primaryInk; case .muted: return Remna.muted }
    }
    static func of(_ status: String) -> RemnaTone {
        switch status.lowercased() {
        case "paid", "fulfilled", "online", "active", "done", "completed", "sent", "enabled", "ok", "answered", "closed": return .ok
        case "pending", "queued", "sending", "creating", "processing", "open", "waiting", "stale", "review": return .warn
        case "failed", "offline", "error", "creation_unknown", "refunded", "disabled", "critical", "restricted": return .bad
        default: return .muted
        }
    }
}

struct RemnaCard<Content: View>: View {
    var title = ""
    var hint = ""
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !title.isEmpty { Text(title).font(.system(size: 16, weight: .semibold)).foregroundStyle(Remna.textStrong) }
            if !hint.isEmpty { Text(hint).font(.footnote).foregroundStyle(Remna.muted) }
            content
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(Remna.surface))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Remna.line, lineWidth: 1))
    }
}

struct RemnaKpi: View {
    let label: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.caption).foregroundStyle(Remna.muted).lineLimit(1)
            Text(value).font(.system(size: 24, weight: .bold, design: .monospaced)).foregroundStyle(Remna.primaryInk).lineLimit(1).minimumScaleFactor(0.6)
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(Remna.surface))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Remna.line, lineWidth: 1))
    }
}

struct RemnaBadge: View {
    let text: String
    var tone: RemnaTone? = nil
    var body: some View {
        let color = (tone ?? RemnaTone.of(text)).color
        Text(text).font(.caption.weight(.semibold)).foregroundStyle(color)
            .padding(.horizontal, 9).padding(.vertical, 3).background(Capsule().fill(color.opacity(0.12)))
    }
}

struct RemnaRow<Actions: View>: View {
    let title: String
    var detail = ""
    var badge = ""
    var tone: RemnaTone? = nil
    @ViewBuilder var actions: Actions
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title).font(.system(size: 15, weight: .medium)).foregroundStyle(Remna.text)
                Spacer()
                if !badge.isEmpty { RemnaBadge(text: badge, tone: tone) }
            }
            if !detail.isEmpty { Text(detail).font(.footnote).foregroundStyle(Remna.muted) }
            HStack(spacing: 8) { actions }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Remna.surface2))
    }
}

extension RemnaRow where Actions == EmptyView {
    init(title: String, detail: String = "", badge: String = "", tone: RemnaTone? = nil) {
        self.init(title: title, detail: detail, badge: badge, tone: tone) { EmptyView() }
    }
}

struct RemnaEmpty: View {
    let text: String
    var body: some View { Text(text).foregroundStyle(Remna.subtle).padding(.vertical, 6) }
}

struct RemnaNotice: View {
    let text: String
    var tone: RemnaTone = .warn
    var body: some View {
        Text(text).font(.subheadline).foregroundStyle(tone.color).padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(tone.color.opacity(0.1)))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(tone.color.opacity(0.35), lineWidth: 1))
    }
}

struct RemnaPrimary: View {
    let title: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(.system(size: 15, weight: .semibold)).foregroundStyle(.white).frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(RoundedRectangle(cornerRadius: 12).fill(Remna.primary))
        }.buttonStyle(.plain)
    }
}

struct RemnaGhost: View {
    let title: String
    var danger = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(.footnote).foregroundStyle(danger ? Remna.danger : Remna.text).padding(.horizontal, 12).padding(.vertical, 7)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(danger ? Remna.danger.opacity(0.5) : Remna.lineStrong, lineWidth: 1))
        }.buttonStyle(.plain)
    }
}

struct RemnaPill: View {
    let title: String
    let selected: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(.system(size: 14, weight: selected ? .semibold : .regular)).foregroundStyle(selected ? Remna.textStrong : Remna.muted)
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(RoundedRectangle(cornerRadius: 10).fill(selected ? Remna.primary.opacity(0.16) : Remna.surface))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(selected ? Remna.primary.opacity(0.5) : Remna.line, lineWidth: 1))
        }.buttonStyle(.plain)
    }
}

struct RemnaField: View {
    let title: String
    @Binding var text: String
    var secure = false
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(Remna.muted)
            Group {
                if secure { SecureField("", text: $text) } else { TextField("", text: $text).textInputAutocapitalization(.never).autocorrectionDisabled() }
            }
            .padding(12).foregroundStyle(Remna.text)
            .background(RoundedRectangle(cornerRadius: 12).fill(Remna.input))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Remna.line, lineWidth: 1))
        }
    }
}
