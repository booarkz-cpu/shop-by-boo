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

    private func t(_ key: String) -> String { loadStrings(lang)[key] ?? key }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    if let logo { Image(uiImage: logo).resizable().frame(width: 48, height: 48) }
                    Text(t("app_name")).font(.title2).foregroundStyle(Color(red: 0.54, green: 0.47, blue: 1.0))
                    Spacer()
                    Button(lang == "ru" ? "EN" : "RU") { lang = lang == "ru" ? "en" : "ru" }
                }
                Text(t("tagline")).foregroundStyle(.secondary)
                if token.isEmpty || unlocked {
                    HStack {
                        Text(base.isEmpty ? t("add_profile") : profileTitle()).foregroundStyle(Color(red: 0.58, green: 0.77, blue: 0.99))
                        Spacer()
                        Button("\(t("profiles")) (\(profiles.count))") { reloadProfiles(); showProfiles.toggle() }
                    }
                }
                if !notice.isEmpty { Text(notice).foregroundStyle(.orange) }
                if showProfiles && (token.isEmpty || unlocked) { profilePanel }
                if token.isEmpty { auth } else if !unlocked { lock } else { home }
            }.padding()
        }
        .background(Color(red: 0.047, green: 0.063, blue: 0.129))
        .preferredColorScheme(.dark)
        .overlay { if scenePhase != .active { Color.black.ignoresSafeArea() } }
        .onAppear {
            if token.isEmpty { loadPublicLogo() }
            else if !unlocked { unlockSavedSession() }
        }
        .onChange(of: token) { value in
            if !value.isEmpty && unlocked { refresh() }
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
    }

    private var profilePanel: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(profiles) { profile in
                let current = profile.id == activeId
                Text("\(profile.title) · \(profile.host)\(profile.email.isEmpty ? "" : " · \(profile.email)") · \(signedInIds.contains(profile.id) ? t("signed_in") : t("signed_out"))\(current ? " · \(t("active_profile"))" : "")")
                HStack {
                    if !current { Button(t("switch_profile")) { switchTo(profile.id) }.disabled(busy) }
                    Button(t("remove_profile"), role: .destructive) { removeProfile(profile) }.disabled(busy)
                }
            }
            Button(t("add_profile")) { addProfile() }.buttonStyle(.borderedProminent).disabled(busy)
        }
    }

    private func profileTitle() -> String { ProfileVault.find(activeId)?.title ?? (URL(string: base)?.host ?? base) }

    private func clearLoaded() {
        overview = [:]; plans = []; payments = []; monitoring = [:]; platform = [:]; ops = [:]
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
        VStack(alignment: .leading, spacing: 8) {
            TextField(t("profile_label"), text: $profileLabel).textFieldStyle(.roundedBorder)
            TextField(t("server"), text: $base).textFieldStyle(.roundedBorder)
            TextField(t("email"), text: $email).textFieldStyle(.roundedBorder)
            SecureField(t("password"), text: $password).textFieldStyle(.roundedBorder)
            TextField(t("otp"), text: $otp).textFieldStyle(.roundedBorder)
            Button(t("sign_in")) { signIn() }.disabled(busy)
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
                    ForEach(["overview", "plans", "payments", "monitoring", "platform", "ops", "support", "broadcast"], id: \.self) { key in
                        Button(t(key)) { tab = key }.buttonStyle(.bordered)
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
            Text("\(t("role")) \(overview["role"] as? String ?? "") · \(t("plans")) \(jsonInt(overview["plans"]) ?? 0) · \(t("payments")) \(jsonInt(overview["payments"]) ?? 0)")
        case "plans":
            if plans.isEmpty { Text(t("no_data")) }
            ForEach(Array(plans.enumerated()), id: \.offset) { _, plan in
                Text("\(plan["name"] as? String ?? "") · \(plan["price"] ?? "") · \(jsonBool(plan["enabled"]) ? t("enabled") : t("disabled"))")
                Button(jsonBool(plan["enabled"]) ? t("disable_plan") : t("enable_plan")) { setPlan(plan, enabled: !jsonBool(plan["enabled"])) }
            }
        case "payments":
            if payments.isEmpty { Text(t("no_data")) }
            ForEach(Array(payments.enumerated()), id: \.offset) { _, payment in
                Text("#\(payment["id"] ?? "") · \(payment["amount"] ?? "") \(payment["currency"] as? String ?? "") · \(payment["status"] as? String ?? "")")
                Button(t("payment_detail")) { loadPayment(payment) }
            }
            if !paymentDetail.isEmpty {
                Text("#\(paymentDetail["id"] ?? "") · \(jsonText(paymentDetail["order_id"])) · \(jsonText(paymentDetail["purpose"])) · \(jsonText(paymentDetail["fulfillment_status"]))")
            }
        case "monitoring":
            if (monitoring["error"] as? String)?.isEmpty == false { Text(t("panel_down")) }
            let nodes = monitoring["nodes"] as? [[String: Any]] ?? []
            if nodes.isEmpty { Text(t("no_data")) }
            ForEach(Array(nodes.enumerated()), id: \.offset) { _, row in
                let node = publicNode(row)
                Text("\(node["name"] as? String ?? "") · \(node["country"] as? String ?? "") · \(node["status"] as? String ?? "") · \(node["users_online"] as? Int ?? 0)")
            }
        case "platform":
            Text(t("violations"))
            let violations = platform["violations"] as? [[String: Any]] ?? []
            if violations.isEmpty { Text(t("no_data")) }
            ForEach(Array(violations.enumerated()), id: \.offset) { _, row in
                Text("#\(row["id"] ?? "") · \(t("score")) \(row["score"] ?? "") · \(row["recommendation"] as? String ?? "")")
                HStack {
                    Button(t("restrict")) { review(row, "restrict") }
                    Button(t("clear")) { review(row, "clear") }
                }
            }
            Text(t("agents"))
            let agents = platform["agents"] as? [[String: Any]] ?? []
            ForEach(Array(agents.enumerated()), id: \.offset) { _, agent in
                Text("\(agent["name"] as? String ?? "") · CPU \(agent["cpu"] ?? "") · \(jsonBool(agent["stale"]) ? t("stale") : t("online"))")
            }
            Text(t("countries"))
            let countries = platform["countries"] as? [[String: Any]] ?? []
            ForEach(Array(countries.enumerated()), id: \.offset) { _, country in
                Text("\(country["country"] as? String ?? ""): \(country["count"] ?? 0)")
            }
        case "ops":
            Text(t("ops")).font(.headline)
            Text("\(t("critical")): \(ops["critical"] ?? 0)")
            Text("\(t("stale_agents")): \(ops["stale_agents"] ?? 0)")
            let agents = ops["agents"] as? [[String: Any]] ?? []
            ForEach(Array(agents.enumerated()), id: \.offset) { _, agent in
                Text("\(jsonText(agent["name"])) · CPU \(jsonText(agent["cpu"])) · RAM \(jsonText(agent["mem"]))")
            }
        case "broadcast":
            Text(t("broadcast_hint")).foregroundStyle(.secondary)
            HStack {
                Button(t("all_telegram")) { broadcastTarget = "all" }.buttonStyle(.bordered)
                Button(t("active_subs")) { broadcastTarget = "active" }.buttonStyle(.bordered)
                Button(t("inactive_subs")) { broadcastTarget = "inactive" }.buttonStyle(.bordered)
            }
            Text(t(broadcastTarget == "active" ? "active_subs" : broadcastTarget == "inactive" ? "inactive_subs" : "all_telegram"))
            TextField(t("broadcast_text"), text: $broadcastText).textFieldStyle(.roundedBorder)
            Button(t("queue_broadcast")) { queueBroadcast() }.disabled(busy)
            if broadcasts.isEmpty { Text(t("no_data")) }
            ForEach(Array(broadcasts.enumerated()), id: \.offset) { _, row in
                let audience = (row["target"] as? String) == "active" ? t("active_subs") : (row["target"] as? String) == "inactive" ? t("inactive_subs") : t("all_telegram")
                Text("#\(row["id"] ?? "") · \(audience) · \(row["status"] as? String ?? "") · \(t("sent")) \(row["sent_count"] ?? 0) · \(t("failed")) \(row["failed_count"] ?? 0)")
                if (row["status"] as? String) == "sending" || (row["status"] as? String) == "failed" {
                    Button(t("retry_broadcast")) { retryBroadcast(row) }.disabled(busy)
                }
            }
        default:
            TextField(t("reply"), text: $reply).textFieldStyle(.roundedBorder)
            if tickets.isEmpty { Text(t("no_data")) }
            ForEach(Array(tickets.enumerated()), id: \.offset) { _, ticket in
                Text("#\(ticket["id"] ?? "") · \(ticket["subject"] as? String ?? "") · \(ticket["status"] as? String ?? "")")
                Text(ticket["message"] as? String ?? "")
                Button(t("send")) { send(ticket) }.disabled(busy)
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
