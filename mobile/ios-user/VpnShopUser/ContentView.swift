import LocalAuthentication
import SwiftUI
import UIKit

struct UserRootView: View {
    @AppStorage("shop_lang") private var lang = UserRootView.detectLanguage()
    @AppStorage("shop_base") private var base = ""
    @State private var token = SessionKeychain.load(baseKey: "shop_base", legacyKey: "shop_token")
    @Environment(\.scenePhase) private var scenePhase
    @State private var authenticationContext: LAContext?
    @State private var email = ""
    @State private var password = ""
    @State private var tab = "overview"
    @State private var notice = ""
    @State private var busy = false
    @State private var dashboard: [String: Any] = [:]
    @State private var profiles: [[String: Any]] = []
    @State private var plans: [[String: Any]] = []
    @State private var builders: [[String: Any]] = []
    @State private var servers: [String: Any] = [:]
    @State private var connection: [String: Any] = [:]
    @State private var config: [String: Any] = [:]
    @State private var promo = ""
    @State private var devices: [[String: Any]] = []
    @State private var notifications: [[String: Any]] = []
    @State private var routing: [String: Any] = [:]
    @State private var features: [String: Any] = [:]
    @State private var diagnostics: [String: Any] = [:]
    @State private var privacy: [String: Any] = [:]
    @State private var liveConnection: [String: Any] = [:]
    @State private var traffic: [String: Any] = [:]
    @State private var giftCode = ""
    @State private var topupAmount = "100"
    @State private var unlocked = false
    @State private var subject = ""
    @State private var message = ""
    @State private var logo: UIImage?
    @ObservedObject private var push = PushCenter.shared
    @State private var pushEnabled = PushCenter.shared.enabled

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

    private var strings: [String: String] { loadStrings(lang) }
    private func t(_ key: String) -> String { strings[key] ?? key }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    if let logo { Image(uiImage: logo).resizable().frame(width: 48, height: 48) }
                    Text(t("app_name")).font(.title2).foregroundStyle(Color(red: 0.54, green: 0.47, blue: 1.0))
                    Spacer()
                    Button(Self.languageLabel(lang)) { lang = Self.nextLanguage(lang) }
                }
                Text(t("tagline")).foregroundStyle(.secondary)
                if !notice.isEmpty { Text(notice).foregroundStyle(.orange) }
                if token.isEmpty { auth } else if !unlocked { lock } else { home }
            }
            .padding()
        }
        .background(Color(red: 0.047, green: 0.063, blue: 0.129))
        .preferredColorScheme(.dark)
        .overlay { if scenePhase != .active { Color.black.ignoresSafeArea() } }
        .onAppear {
            if token.isEmpty { loadPublicLogo() }
            else if !unlocked { unlockSavedSession() }
        }
        .onChange(of: token) { value in
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
        .onChange(of: lang) { _ in if !token.isEmpty && unlocked { refresh() } }
        .onChange(of: push.openNotifications) { open in
            if open { tab = "notifications"; push.openNotifications = false }
        }
    }

    private var auth: some View {
        VStack(alignment: .leading, spacing: 8) {
            field(t("server"), text: $base)
            field(t("email"), text: $email)
            SecureField(t("password"), text: $password).textFieldStyle(.roundedBorder)
            Button(t("sign_in")) { authenticate("/api/auth/login") }.disabled(busy)
            Button(t("sign_up")) { authenticate("/api/auth/register") }.disabled(busy)
        }
    }

    private var lock: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(t("unlock")) { unlockSavedSession() }.buttonStyle(.borderedProminent)
            Button(t("sign_out")) { signOut() }
        }
    }

    private var home: some View {
        VStack(alignment: .leading, spacing: 10) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(["overview", "plans", "builder", "servers", "connection", "devices", "notifications", "security", "diagnostics", "privacy", "support"], id: \.self) { key in
                        Button(t(key)) { tab = key }.buttonStyle(.bordered).tint(tab == key ? Color(red: 0.54, green: 0.47, blue: 1.0) : .gray)
                    }
                }
            }
            Button(t("refresh")) { refresh() }.disabled(busy)
            Button(t("sign_out")) { signOut() }
            section
        }
    }

    @ViewBuilder private var section: some View {
        switch tab {
        case "overview":
            Text(t("my_subscriptions")).font(.headline)
            ForEach(Array(profiles.enumerated()), id: \.offset) { _, profile in
                Text("\(jsonText(profile["name"])) · \(jsonText(profile["plan"])) · \(jsonText(profile["expires_at"]))")
                if jsonBool(profile["is_primary"]) { Text(t("selected_subscription")) }
                else { Button(t("select_subscription")) { selectProfile(profile) }.disabled(busy) }
            }
            let user = dashboard["user"] as? [String: Any] ?? [:]
            Text("\(t("wallet")): \(user["wallet_balance"] as? String ?? "0")")
            Text("\(t("referral")): \(user["referral_code"] as? String ?? "")")
            if dashboard["subscription"] == nil || dashboard["subscription"] is NSNull {
                Text(t("no_subscription"))
            } else {
                Text(t("active"))
            }
            Text("\(t("traffic_used")): \(jsonBool(traffic["available"]) ? jsonText(traffic["traffic_used_bytes"]) : t("usage_unavailable"))")
            Text("\(t("traffic_limit")): \(jsonText(traffic["traffic_limit_bytes"]).isEmpty ? t("unlimited") : jsonText(traffic["traffic_limit_bytes"]))")
            field(t("topup_amount"), text: $topupAmount)
            Button(t("topup")) { topUp() }.disabled(busy)
            field(t("gift_code"), text: $giftCode)
            Button(t("redeem")) { redeemGift() }.disabled(busy)
        case "plans":
            field(t("promo"), text: $promo)
            ForEach(Array(plans.enumerated()), id: \.offset) { _, plan in
                Text("\(jsonText(plan["name"])) · \(jsonText(plan["price"]))")
                Button(t("pay")) { buy(plan, wallet: false) }
                Button(t("pay_wallet")) { buy(plan, wallet: true) }
            }
        case "builder":
            ForEach(Array(builders.enumerated()), id: \.offset) { _, row in
                Text(row["name"] as? String ?? "")
                Button(t("pay")) { buyConstructor(row) }
            }
        case "servers":
            if (servers["error"] as? String)?.isEmpty == false { Text(t("panel_down")) }
            let nodes = servers["nodes"] as? [[String: Any]] ?? []
            if nodes.isEmpty { Text(t("nodes_empty")) }
            ForEach(Array(nodes.enumerated()), id: \.offset) { _, row in
                let node = publicNode(row)
                Text("\(node["name"] as? String ?? "") · \(node["country"] as? String ?? "") · \(t(node["status"] as? String ?? "unknown")) · \(node["users_online"] as? Int ?? 0)")
            }
        case "connection":
            let url = connection["subscription_url"] as? String ?? ""
            Text(url.isEmpty ? t("no_subscription") : url)
            if !url.isEmpty {
                Button(t("copy")) {
                    UIPasteboard.general.string = url
                    notice = t("copied")
                }
                ForEach(subscriptionApps(url), id: \.0) { item in
                    Button(item.0) {
                        if let target = URL(string: item.1) { UIApplication.shared.open(target) }
                    }
                }
            }
            Text(t("guides"))
            let platforms = connection["platforms"] as? [String: Any] ?? [:]
            ForEach(["android", "ios", "tv", "windows", "macos", "linux"], id: \.self) { key in
                Text("\(key): \(jsonText(platforms[key]))")
            }
            Button(t("trial")) { startTrial() }
        case "notifications":
            Text(t("push_title")).font(.headline)
            Text(pushEnabled ? t("push_on") : t("push_off")).foregroundStyle(.secondary)
            if pushEnabled {
                Button(t("push_disable")) { disablePush() }.disabled(busy)
                Button(t("push_test")) { testPush() }.disabled(busy)
            } else {
                Button(t("push_enable")) { enablePush() }.buttonStyle(.borderedProminent).disabled(busy)
            }
            if notifications.isEmpty { Text(t("no_notifications")) }
            ForEach(Array(notifications.enumerated()), id: \.offset) { _, n in
                VStack(alignment: .leading) {
                    Text(jsonText(n["title"])).font(.headline)
                    Text(jsonText(n["body"])).foregroundStyle(.secondary)
                    if !(n["read"] as? Bool ?? false) { Button(t("mark_read")) { markNotification(n) } }
                }
            }
        case "security":
            Text(t("security")).font(.headline)
            Text("Biometric unlock: ON")
            if let rec = routing["recommendation"] as? [String: Any] { Text("\(t("recommended")): \(jsonText(rec["name"])) · \(jsonText(rec["country"]))") }
            Button(t("unlock")) { unlockSavedSession() }.buttonStyle(.borderedProminent)
        case "diagnostics":
            Text("Corgi Diagnostics").font(.headline)
            Text("Status: \(jsonText(diagnostics["overall"]))")
            let checks = diagnostics["checks"] as? [[String: Any]] ?? []
            ForEach(Array(checks.enumerated()), id: \.offset) { _, c in Text("\(jsonText(c["name"])) · \(jsonText(c["status"])) · \(jsonText(c["detail"]))") }
            Text("Server: \(jsonText((liveConnection["server"] as? [String: Any])?["name"]))")
            Text("Latency: \(jsonText(liveConnection["latency_ms"])) ms")
            Text("Packet loss: \(jsonText(liveConnection["packet_loss_percent"]))%")
        case "privacy":
            Text("Privacy Dashboard").font(.headline)
            Text("DNS protected: \(jsonBool(privacy["dns_protected"]))")
            Text("IPv6 protected: \(jsonBool(privacy["ipv6_protected"]))")
            Text("Kill Switch: \(jsonBool(privacy["kill_switch"]))")
            Text("Protected traffic: \(jsonText(privacy["protected_traffic_bytes"]))")
            Text("Family Plan: available · Business VPN: available")
            Text("Referral & Rewards: available")
        case "devices":
            if devices.isEmpty { Text(t("no_devices")) }
            ForEach(Array(devices.enumerated()), id: \.offset) { _, device in
                Text("\(jsonText(device["name"])) · \(jsonText(device["platform"])) · \(jsonText(device["status"]))")
                if jsonText(device["status"]) == "active" {
                    Button(t("revoke")) { revokeDevice(device) }
                }
            }
        default:
            field(t("subject"), text: $subject)
            field(t("message"), text: $message)
            Button(t("send")) { sendTicket() }.disabled(busy)
        }
    }

    private func field(_ title: String, text: Binding<String>) -> some View {
        TextField(title, text: text).textFieldStyle(.roundedBorder)
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

    private func refresh() {
        work {
            let api = ShopClient(base: base, token: token, lang: lang)
            let nextDashboard = try api.call("GET", "/api/me/dashboard") as? [String: Any] ?? [:]
            let nextProfiles = try api.call("GET", "/api/me/subscriptions") as? [[String: Any]] ?? []
            let nextPlans = try api.call("GET", "/api/plans") as? [[String: Any]] ?? []
            let nextBuilders = try api.call("GET", "/api/tariff-constructors") as? [[String: Any]] ?? []
            let nextServers = try api.call("GET", "/api/me/servers") as? [String: Any] ?? [:]
            let nextConnection = try api.call("GET", "/api/me/connection-info") as? [String: Any] ?? [:]
            let nextConfig = try api.call("GET", "/api/public/config") as? [String: Any] ?? [:]
            let nextTraffic = try api.call("GET", "/api/me/traffic") as? [String: Any] ?? [:]
            let nextDevices = try api.call("GET", "/api/me/devices") as? [[String: Any]] ?? []
            let nextNotifications = try api.call("GET", "/api/me/mobile/notifications?unread_only=false") as? [[String: Any]] ?? []
            let nextRouting = try api.call("GET", "/api/me/routing/recommendation") as? [String: Any] ?? [:]
            let nextFeatures = try api.call("GET", "/api/me/mobile/features") as? [String: Any] ?? [:]
            let nextDiagnostics = try api.call("GET", "/api/me/mobile/diagnostics") as? [String: Any] ?? [:]
            let nextPrivacy = try api.call("GET", "/api/me/mobile/privacy") as? [String: Any] ?? [:]
            let nextLiveConnection = try api.call("GET", "/api/me/mobile/connection") as? [String: Any] ?? [:]
            let nextLogo = logoImage(api, "/api/public/apps")
            // Re-bind a rotated APNs token, or the same token to a re-issued session.
            if PushCenter.shared.enabled, let current = PushCenter.shared.latestToken {
                _ = try? PushCenter.register(base: base, session: token, lang: lang, token: current)
            }
            DispatchQueue.main.async {
                dashboard = nextDashboard
                profiles = nextProfiles
                plans = nextPlans
                builders = nextBuilders
                servers = nextServers
                connection = nextConnection
                config = nextConfig
                traffic = nextTraffic
                devices = nextDevices
                notifications = nextNotifications
                routing = nextRouting
                logo = nextLogo
            }
        }
    }

    private func markNotification(_ row: [String: Any]) {
        guard let id = jsonInt(row["id"]) else { return }
        work { _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/mobile/notifications/\(id)/read"); refresh() }
    }

    private func signOut() {
        let previous = token
        let origin = base
        token = ""
        SessionKeychain.clear()
        unlocked = false
        pushEnabled = false
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

    private func testPush() {
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/push/test", body: [:])
            DispatchQueue.main.async { notice = t("push_test_sent") }
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
        work {
            let response = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/wallet/topup", body: ["amount": topupAmount, "provider": providerName()], idempotency: UUID().uuidString) as? [String: Any]
            DispatchQueue.main.async { notice = t("topup_ok"); openPayment(response?["url"] as? String ?? "") }
        }
    }

    private func redeemGift() {
        let code = giftCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !code.isEmpty else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/gifts/redeem", body: ["code": code])
            DispatchQueue.main.async { notice = t("gift_ok"); giftCode = "" }
        }
    }

    private func revokeDevice(_ device: [String: Any]) {
        guard let id = jsonInt(device["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/devices/\(id)/revoke", body: [:])
            DispatchQueue.main.async { notice = t("device_revoked") }
        }
    }

    private func selectProfile(_ profile: [String: Any]) {
        guard let id = jsonInt(profile["id"]) else { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/subscriptions/\(id)/select")
            DispatchQueue.main.async { refresh() }
        }
    }

    private func buy(_ plan: [String: Any], wallet: Bool) {
        guard let id = jsonInt(plan["id"]) else { return }
        work {
            var body: [String: Any] = ["plan_id": id]
            if let sub = dashboard["subscription"] as? [String: Any], let selected = jsonInt(sub["id"]) { body["subscription_id"] = selected }
            if !promo.trimmingCharacters(in: .whitespaces).isEmpty { body["promo_code"] = promo }
            let api = ShopClient(base: base, token: token, lang: lang)
            if wallet {
                _ = try api.call("POST", "/api/me/wallet/spend", body: body, idempotency: UUID().uuidString)
                DispatchQueue.main.async { notice = t("paid_wallet") }
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

    private func buyConstructor(_ row: [String: Any]) {
        guard let id = jsonInt(row["id"]) else { return }
        let options = row["options"] as? [[String: Any]] ?? []
        var picked: [String: Int] = [:]
        for kind in ["devices", "traffic_gb", "days"] {
            if let option = options.first(where: { ($0["kind"] as? String) == kind }), let optionId = jsonInt(option["id"]) {
                picked[kind] = optionId
            }
        }
        work {
            var body: [String: Any] = [
                "constructor_id": id,
                "provider": providerName(),
                "device_option_id": picked["devices"] ?? 0,
                "traffic_option_id": picked["traffic_gb"] ?? 0,
                "days_option_id": picked["days"] ?? 0,
            ]
            if let sub = dashboard["subscription"] as? [String: Any], let selected = jsonInt(sub["id"]) { body["subscription_id"] = selected }
            let response = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/payments/create", body: body, idempotency: UUID().uuidString) as? [String: Any]
            DispatchQueue.main.async {
                notice = t("payment_created")
                openPayment(response?["url"] as? String ?? "")
            }
        }
    }

    private func startTrial() {
        guard let plan = plans.first, let id = jsonInt(plan["id"]) else { return }
        let days = jsonInt(config["trial_days"]) ?? 3
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/trial", body: ["plan_id": id, "days": days])
            DispatchQueue.main.async { notice = t("trial_started") }
        }
    }

    private func sendTicket() {
        let title = subject.trimmingCharacters(in: .whitespaces)
        let text = message.trimmingCharacters(in: .whitespaces)
        if title.isEmpty || text.isEmpty { return }
        work {
            _ = try ShopClient(base: base, token: token, lang: lang).call("POST", "/api/me/support/tickets", body: ["subject": title, "message": text])
            DispatchQueue.main.async { notice = t("ticket_sent"); subject = ""; message = "" }
        }
    }

    private func providerName() -> String {
        let providers = config["payment_providers"] as? [String] ?? []
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
