import CryptoKit
import Foundation
import SwiftUI
import UIKit

// MARK: - Layout of the app (GET /api/mobile/layout, edited in the admin panel)

struct LayoutButton: Identifiable, Equatable {
    let id: String
    let label: String
    let action: String
    let target: String
    let style: String
    let icon: String
    let audience: String
}

struct LayoutBanner: Equatable {
    let url: String
    let link: String
}

struct LayoutSection: Identifiable {
    let id: String
    let kind: String
    let tab: Bool
    let title: String
    let subtitle: String
    let body: String
    let icon: String
    let banner: LayoutBanner?
    let buttons: [LayoutButton]
}

struct LayoutTheme {
    var accent = Color(hex: "#FF8A1F")
    var accent2 = Color(hex: "#FFC069")
    var background = Color(hex: "#0E0F14")
    var surface = Color(hex: "#1A1C24")
    var surface2 = Color(hex: "#252833")
    var text = Color(hex: "#F5F2EE")
    var muted = Color(hex: "#9A97A3")
    var success = Color(hex: "#3DDC84")
    var danger = Color(hex: "#FF5A6E")
    var radius: CGFloat = 22
}

/// Actions the app implements; a button with anything else is not drawn.
let knownActions: Set<String> = [
    "connect", "open", "url", "document", "cabinet", "telegram_channel", "import_app", "copy_subscription", "show_qr", "copy_id",
    "buy", "pay_wallet", "trial", "topup", "redeem", "auto_location", "share_referral", "copy_referral", "family_invite",
    "support_ticket", "report_problem", "language", "push_toggle", "widget_toggle", "passkey_add", "refresh", "sign_out",
]

struct AppLayout {
    var lang = "ru"
    var version = ""
    var theme = LayoutTheme()
    var texts: [String: String] = [:]
    var tabs: [String] = []
    var sections: [LayoutSection] = []
    var links: [String: String] = [:]
    /// Replacements of the app strings (l10n.json keys) set in the admin panel.
    var strings: [String: String] = [:]
    /// Screen blocks switched on or off in the admin panel; missing means on.
    var features: [String: Bool] = [:]

    func section(_ id: String) -> LayoutSection? { sections.first { $0.id == id } }
    func text(_ key: String) -> String { texts[key] ?? key }
    func feature(_ key: String) -> Bool { features[key] ?? true }

    init() {}

    init(_ doc: [String: Any]) {
        lang = doc["lang"] as? String ?? "ru"
        version = doc["version"] as? String ?? ""
        let t = doc["theme"] as? [String: Any] ?? [:]
        func c(_ key: String, _ fallback: Color) -> Color {
            guard let raw = t[key] as? String, raw.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil else { return fallback }
            return Color(hex: raw)
        }
        let d = LayoutTheme()
        theme = LayoutTheme(accent: c("accent", d.accent), accent2: c("accent_2", d.accent2), background: c("background", d.background),
                            surface: c("surface", d.surface), surface2: c("surface_2", d.surface2), text: c("text", d.text),
                            muted: c("muted", d.muted), success: c("success", d.success), danger: c("danger", d.danger),
                            radius: CGFloat(min(max(jsonInt(t["radius"]) ?? 22, 0), 40)))
        texts = (doc["texts"] as? [String: Any] ?? [:]).compactMapValues { $0 as? String }
        links = (doc["links"] as? [String: Any] ?? [:]).compactMapValues { $0 as? String }
        strings = (doc["strings"] as? [String: Any] ?? [:]).compactMapValues { ($0 as? String).flatMap { $0.isEmpty ? nil : $0 } }
        features = (doc["features"] as? [String: Any] ?? [:]).compactMapValues { $0 as? Bool }
        sections = (doc["sections"] as? [[String: Any]] ?? []).map { s in
            let buttons: [LayoutButton] = (s["buttons"] as? [[String: Any]] ?? []).compactMap { b in
                let action = jsonText(b["action"])
                guard knownActions.contains(action) else { return nil }
                return LayoutButton(id: jsonText(b["id"]), label: jsonText(b["label"]), action: action, target: jsonText(b["target"]),
                                    style: b["style"] as? String ?? "secondary", icon: jsonText(b["icon"]), audience: b["audience"] as? String ?? "any")
            }
            var banner: LayoutBanner?
            if let raw = s["banner"] as? [String: Any], !jsonText(raw["url"]).isEmpty {
                banner = LayoutBanner(url: jsonText(raw["url"]), link: jsonText(raw["link"]))
            }
            return LayoutSection(id: jsonText(s["id"]), kind: jsonText(s["kind"]), tab: jsonBool(s["tab"]), title: jsonText(s["title"]),
                                 subtitle: jsonText(s["subtitle"]), body: jsonText(s["body"]), icon: jsonText(s["icon"]), banner: banner, buttons: buttons)
        }
        let ids = Set(sections.map(\.id))
        tabs = (doc["tabs"] as? [String] ?? []).filter { ids.contains($0) }
    }
}

/// Layout source: the shop (ETag revalidation), the copy saved after the last success, the bundled default.
enum LayoutStore {
    static func bundled(_ lang: String) -> AppLayout {
        guard let url = Bundle.main.url(forResource: "default_layout", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let all = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return AppLayout() }
        return AppLayout(all[lang] as? [String: Any] ?? all["ru"] as? [String: Any] ?? [:])
    }

    static func cached(base: String, lang: String) -> AppLayout? {
        guard let data = UserDefaults.standard.data(forKey: "layout_doc:\(base):\(lang)"),
              let doc = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return AppLayout(doc)
    }

    /// Blocking: call from a background queue. nil when unchanged or unreachable.
    static func fetch(base: String, lang: String) -> AppLayout? {
        guard let url = URL(string: "\(base)/api/mobile/layout?lang=\(lang)") else { return nil }
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("ios-user", forHTTPHeaderField: "X-Shop-Client")
        let defaults = UserDefaults.standard
        if defaults.data(forKey: "layout_doc:\(base):\(lang)") != nil, let etag = defaults.string(forKey: "layout_etag:\(base):\(lang)") {
            request.setValue(etag, forHTTPHeaderField: "If-None-Match")
        }
        let semaphore = DispatchSemaphore(value: 0)
        var result: AppLayout?
        URLSession.shared.dataTask(with: request) { data, response, _ in
            defer { semaphore.signal() }
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let data, data.count < 512 * 1024,
                  let doc = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            defaults.set(data, forKey: "layout_doc:\(base):\(lang)")
            defaults.set(http.value(forHTTPHeaderField: "ETag") ?? "", forKey: "layout_etag:\(base):\(lang)")
            result = AppLayout(doc)
        }.resume()
        semaphore.wait()
        return result
    }
}

extension Color {
    init(hex: String) {
        let value = UInt64(hex.dropFirst(), radix: 16) ?? 0
        self.init(red: Double((value >> 16) & 0xFF) / 255, green: Double((value >> 8) & 0xFF) / 255, blue: Double(value & 0xFF) / 255)
    }
}

/// Icon names of the layout → SF Symbols.
func layoutSymbol(_ name: String) -> String? {
    let map: [String: String] = [
        "power": "power", "shield": "shield.fill", "globe": "globe", "star": "star.fill", "crown": "crown.fill", "user": "person.fill",
        "settings": "gearshape.fill", "headset": "headphones", "message": "message.fill", "send": "paperplane.fill", "bell": "bell.fill",
        "bug": "ant.fill", "rocket": "bolt.fill", "gift": "gift.fill", "wallet": "wallet.pass.fill", "card": "creditcard.fill",
        "users": "person.2.fill", "heart": "heart.fill", "smartphone": "iphone", "plus": "plus", "copy": "doc.on.doc",
        "share": "square.and.arrow.up", "link": "link", "key": "key.fill", "lock": "lock.fill", "info": "info.circle.fill",
        "file": "doc.text.fill", "help": "questionmark.circle.fill", "server": "server.rack", "activity": "waveform.path.ecg",
        "zap": "bolt.fill", "clock": "clock.fill", "refresh": "arrow.clockwise", "logout": "rectangle.portrait.and.arrow.right",
        "language": "globe", "sliders": "slider.horizontal.3", "qr": "qrcode", "download": "arrow.down.circle.fill",
        "trophy": "trophy.fill", "home": "house.fill",
    ]
    return map[name]
}

func flagEmoji(_ country: String) -> String {
    let code = country.trimmingCharacters(in: .whitespaces).uppercased()
    guard code.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil else { return "🌐" }
    return code.unicodeScalars.compactMap { UnicodeScalar(0x1F1E6 + $0.value - 65) }.map { String($0) }.joined()
}

// MARK: - VPN clients and VPN state

/// Without the embedded tunnel (CorgiTunnelManager.available is false) the «Подключить» button
/// hands the subscription to a VPN client and reads whether a VPN tunnel is up on the phone.
enum VpnClients {
    struct Client { let id: String; let title: String; let scheme: String; let store: String }
    static let all = [
        Client(id: "happ", title: "Happ", scheme: "happ", store: "https://apps.apple.com/app/happ-proxy-utility/id6504287215"),
        Client(id: "v2raytun", title: "v2RayTun", scheme: "v2raytun", store: "https://apps.apple.com/app/v2raytun/id6476628951"),
        Client(id: "streisand", title: "Streisand", scheme: "streisand", store: ""),
    ]

    static func importURL(_ clientId: String, _ subscription: String) -> URL? {
        guard subscription.hasPrefix("https://"), !subscription.contains(where: { $0.isWhitespace }),
              let encoded = subscription.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return nil }
        switch clientId {
        case "happ": return URL(string: "happ://add/\(encoded)")
        case "v2raytun": return URL(string: "v2raytun://import/\(encoded)")
        case "streisand": return URL(string: "streisand://import/\(encoded)")
        case "hiddify": return URL(string: "hiddify://import/\(encoded)")
        default: return nil
        }
    }

    static func installed() -> [Client] {
        all.filter { client in URL(string: "\(client.scheme)://").map { UIApplication.shared.canOpenURL($0) } ?? false }
    }

    enum Result { case imported, opened, noClient, noSubscription }

    static func connect(_ subscription: String) -> Result {
        guard subscription.hasPrefix("https://") else { return .noSubscription }
        let defaults = UserDefaults.standard
        let clients = installed()
        guard let client = clients.first(where: { $0.id == defaults.string(forKey: "vpn_client") }) ?? clients.first else { return .noClient }
        // A stable fingerprint of the subscription (hashValue changes on every launch).
        let digest = SHA256.hash(data: Data(subscription.utf8)).prefix(8).map { String(format: "%02x", $0) }.joined()
        let marker = "vpn_imported:\(client.id):\(digest)"
        if !defaults.bool(forKey: marker), let url = importURL(client.id, subscription) {
            UIApplication.shared.open(url)
            defaults.set(true, forKey: marker)
            defaults.set(client.id, forKey: "vpn_client")
            return .imported
        }
        if let url = URL(string: "\(client.scheme)://") { UIApplication.shared.open(url) }
        return .opened
    }

    static func importInto(_ clientId: String, _ subscription: String) -> Bool {
        guard let url = importURL(clientId, subscription), let probe = URL(string: "\(clientId)://"),
              UIApplication.shared.canOpenURL(probe) else { return false }
        UIApplication.shared.open(url)
        UserDefaults.standard.set(clientId, forKey: "vpn_client")
        return true
    }

    /// A VPN interface (utun, ipsec, ppp, tap, tun) in the scoped proxy settings means a tunnel is up.
    static func vpnActive() -> Bool {
        guard let settings = CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any],
              let scoped = settings["__SCOPED__"] as? [String: Any] else { return false }
        return scoped.keys.contains { key in ["tap", "tun", "ppp", "ipsec", "utun"].contains { key.hasPrefix($0) } }
    }
}

// MARK: - Shop data

struct ShopData {
    var dashboard: [String: Any] = [:]
    var profiles: [[String: Any]] = []
    var plans: [[String: Any]] = []
    var servers: [String: Any] = [:]
    var connection: [String: Any] = [:]
    var traffic: [String: Any] = [:]
    var devices: [[String: Any]] = []
    var notifications: [[String: Any]] = []
    var routing: [String: Any] = [:]
    var family: [String: Any] = [:]
    var status: [String: Any] = [:]
    var passkeys: [[String: Any]] = []
    var config: [String: Any] = [:]
    var qr: UIImage?
    /// Published shop documents (GET /api/public/info-pages): kind, title, banner.
    var docs: [[String: Any]] = []
    /// Giveaways and wheel campaigns (GET /api/me/giveaways → items).
    var giveaways: [[String: Any]] = []

    /// The first giveaway the customer can still join: the home screen promo banner.
    var openGiveaway: [String: Any]? {
        giveaways.first { jsonText($0["phase"]) == "open" && ($0["my_entry"] == nil || $0["my_entry"] is NSNull) }
    }

    var user: [String: Any] { dashboard["user"] as? [String: Any] ?? [:] }
    var subscription: [String: Any]? { dashboard["subscription"] as? [String: Any] }
    var expires: String { String(jsonText(subscription?["expires_at"]).prefix(10)) }
    var daysLeft: Int? {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "UTC")
        guard let date = f.date(from: expires) else { return nil }
        return Calendar.current.dateComponents([.day], from: Calendar.current.startOfDay(for: Date()), to: date).day
    }
    var subscribed: Bool {
        guard let sub = subscription else { return false }
        if ["expired", "cancelled"].contains(jsonText(sub["status"])) { return false }
        return (daysLeft ?? 0) >= 0
    }
    var subscriptionUrl: String {
        let url = jsonText(connection["subscription_url"]).isEmpty ? jsonText(subscription?["subscription_url"]) : jsonText(connection["subscription_url"])
        return url.hasPrefix("https://") ? url : ""
    }
    var customerId: String {
        let code = jsonText(user["referral_code"])
        return code.isEmpty ? (jsonInt(user["id"]).map(String.init) ?? "") : code
    }
    var nodes: [[String: Any]] { (servers["nodes"] as? [[String: Any]] ?? []).map(publicNode) }
    var currentPlan: [String: Any]? { plans.first { jsonInt($0["id"]) == jsonInt(subscription?["plan_id"]) } }
    var activeDevices: Int { devices.filter { jsonText($0["status"]) == "active" }.count }
}

enum VpnState { case off, connecting, on }

func formatBytes(_ bytes: Double) -> String {
    let gb = bytes / 1_000_000_000
    return gb >= 10 ? String(format: "%.0f GB", gb) : String(format: "%.1f GB", gb)
}

func monthlyPrice(_ plan: [String: Any]) -> Double {
    let raw = jsonText(plan["final_price"]).isEmpty ? jsonText(plan["price"]) : jsonText(plan["final_price"])
    let days = max(jsonInt(plan["duration_days"]) ?? 30, 1)
    return (Double(raw) ?? 0) * 30 / Double(days)
}

// MARK: - Components

/// Default Lusi banners ship in the app (Banners/), uploads come from the shop.
final class BannerLoader: ObservableObject {
    static var cache: [String: UIImage] = [:]
    @Published var image: UIImage?

    func load(base: String, url: String) {
        if let match = url.range(of: "^/api/bot/banners/default/[a-z0-9-]{1,48}\\.jpg$", options: .regularExpression) {
            let name = String(url[match].split(separator: "/").last ?? "").replacingOccurrences(of: ".jpg", with: "")
            if let path = Bundle.main.path(forResource: name, ofType: "jpg", inDirectory: "Banners"), let local = UIImage(contentsOfFile: path) {
                image = local
                return
            }
        }
        let full: String
        if url.hasPrefix("https://") { full = url }
        else if url.range(of: "^/(api/bot/banners/default/[a-z0-9-]{1,48}\\.jpg|media/[A-Za-z0-9._-]{1,120})$", options: .regularExpression) != nil, !base.isEmpty { full = base + url }
        else { return }
        if let cached = Self.cache[full] { image = cached; return }
        guard let target = URL(string: full) else { return }
        URLSession.shared.dataTask(with: target) { data, response, _ in
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let data, data.count < 4 * 1024 * 1024,
                  let img = UIImage(data: data) else { return }
            DispatchQueue.main.async { Self.cache[full] = img; self.image = img }
        }.resume()
    }
}

struct SectionBannerView: View {
    let base: String
    let banner: LayoutBanner?
    let theme: LayoutTheme
    let onLink: (String) -> Void
    @StateObject private var loader = BannerLoader()

    var body: some View {
        if let banner {
            ZStack {
                RoundedRectangle(cornerRadius: theme.radius).fill(theme.surface)
                if let image = loader.image { Image(uiImage: image).resizable().scaledToFill() }
            }
            .aspectRatio(2.5, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: theme.radius))
            .onTapGesture { if !banner.link.isEmpty { onLink(banner.link) } }
            .onAppear { loader.load(base: base, url: banner.url) }
            .accessibilityHidden(true)
        }
    }
}

struct PowerButton: View {
    let state: VpnState
    let theme: LayoutTheme
    let label: String
    let action: () -> Void
    @State private var breathe = false

    var body: some View {
        let ring = state == .on ? theme.success : state == .connecting ? theme.accent2 : theme.accent
        Button(action: action) {
            ZStack {
                Circle().fill(RadialGradient(colors: [ring.opacity(0.35), .clear], center: .center, startRadius: 40, endRadius: 120))
                    .frame(width: 236, height: 236)
                    .scaleEffect(state == .off ? 1 : (breathe ? 1.06 : 0.92))
                Circle().fill(LinearGradient(colors: [theme.surface2, theme.surface], startPoint: .top, endPoint: .bottom))
                    .frame(width: 176, height: 176)
                    .overlay(Circle().stroke(ring, lineWidth: 3))
                Image(systemName: "power").font(.system(size: 66, weight: .semibold)).foregroundStyle(ring)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .onAppear { withAnimation(.easeInOut(duration: 1.4).repeatForever(autoreverses: true)) { breathe = true } }
    }
}

struct StatusPill: View {
    let text: String
    let color: Color
    let theme: LayoutTheme
    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(color).frame(width: 9, height: 9)
            Text(text).font(.system(size: 16, weight: .semibold)).foregroundStyle(theme.text)
        }
        .padding(.horizontal, 18).padding(.vertical, 10)
        .background(Capsule().fill(theme.surface))
    }
}

struct ActionButtonView: View {
    let button: LayoutButton
    let theme: LayoutTheme
    var enabled = true
    let action: () -> Void

    var body: some View {
        let fg: Color = ["primary", "accent"].contains(button.style) ? Color(hex: "#1A0F05") : button.style == "danger" ? theme.danger : theme.text
        Button(action: action) {
            HStack(spacing: 10) {
                if let symbol = layoutSymbol(button.icon) { Image(systemName: symbol) }
                Text(button.label).fontWeight(.bold).lineLimit(1)
            }
            .font(.system(size: 16))
            .foregroundStyle(fg)
            .frame(maxWidth: .infinity, minHeight: 56)
            .background {
                let shape = RoundedRectangle(cornerRadius: theme.radius)
                switch button.style {
                case "primary": shape.fill(LinearGradient(colors: [theme.accent, theme.accent2], startPoint: .leading, endPoint: .trailing))
                case "accent": shape.fill(theme.accent2)
                case "ghost": shape.stroke(theme.surface2, lineWidth: 1)
                default: shape.fill(theme.surface)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.5)
    }
}

struct ActionRowView: View {
    let button: LayoutButton
    let theme: LayoutTheme
    var value = ""
    var toggled: Bool?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 16) {
                if let symbol = layoutSymbol(button.icon) {
                    Image(systemName: symbol).frame(width: 24).foregroundStyle(button.style == "danger" ? theme.danger : button.style == "primary" ? theme.accent : theme.text)
                }
                Text(button.label).font(.system(size: 16, weight: .semibold)).foregroundStyle(button.style == "danger" ? theme.danger : theme.text)
                Spacer()
                if !value.isEmpty { Text(value).foregroundStyle(theme.muted) }
                if let toggled {
                    Toggle("", isOn: .constant(toggled)).labelsHidden().tint(theme.accent).allowsHitTesting(false)
                } else {
                    Image(systemName: "chevron.right").foregroundStyle(theme.muted)
                }
            }
            .padding(.horizontal, 18).padding(.vertical, 16)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct CardView<Content: View>: View {
    let theme: LayoutTheme
    @ViewBuilder let content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 8) { content() }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: theme.radius).fill(theme.surface))
    }
}

struct LoadBars: View {
    let level: Int
    let color: Color
    let theme: LayoutTheme
    var body: some View {
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(1...5, id: \.self) { i in
                RoundedRectangle(cornerRadius: 2).fill(i <= level ? color : theme.muted.opacity(0.3)).frame(width: 5, height: CGFloat(6 + i * 3))
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(Capsule().fill(theme.surface2))
    }
}

struct BottomBar: View {
    let layout: AppLayout
    let current: String
    let onSelect: (String) -> Void

    var body: some View {
        let theme = layout.theme
        HStack {
            ForEach(layout.tabs, id: \.self) { id in
                if let section = layout.section(id) {
                    let tint = id == current ? theme.accent : theme.muted
                    Button { onSelect(id) } label: {
                        if section.kind == "vpn" {
                            Text(section.title).font(.system(size: 17, weight: .bold)).foregroundStyle(tint)
                                .padding(.horizontal, 18).padding(.vertical, 8)
                                .overlay(RoundedRectangle(cornerRadius: 14).stroke(tint, lineWidth: 2))
                        } else {
                            VStack(spacing: 4) {
                                if let symbol = layoutSymbol(section.icon) { Image(systemName: symbol).font(.system(size: 22)) }
                                Text(section.title).font(.system(size: 11, weight: .semibold)).lineLimit(1)
                            }
                            .foregroundStyle(tint)
                        }
                    }
                    .buttonStyle(.plain)
                    .frame(maxWidth: .infinity)
                    .accessibilityAddTraits(id == current ? .isSelected : [])
                }
            }
        }
        .padding(.horizontal, 6).padding(.top, 10).padding(.bottom, 6)
        .background(theme.background)
    }
}

struct BrandTitle: View {
    let brand: String
    let theme: LayoutTheme
    var body: some View {
        let words = brand.split(separator: " ").map(String.init)
        if words.count > 1 {
            (Text(words.dropLast().joined(separator: " ") + " ").font(.system(size: 30, weight: .light)).foregroundColor(theme.text)
             + Text(words.last ?? "").font(.system(size: 30, weight: .black)).foregroundColor(theme.accent))
        } else {
            Text(brand).font(.system(size: 30, weight: .black)).foregroundColor(theme.accent)
        }
    }
}

struct InputField: View {
    let title: String
    @Binding var text: String
    let theme: LayoutTheme
    var secure = false
    var body: some View {
        Group {
            if secure { SecureField(title, text: $text) } else { TextField(title, text: $text) }
        }
        .textInputAutocapitalization(.never)
        .autocorrectionDisabled()
        .padding(16)
        .foregroundStyle(theme.text)
        .background(RoundedRectangle(cornerRadius: 16).fill(theme.surface))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(theme.surface2))
    }
}

// MARK: - Documents («Бот и кабинет → Документы»)

/// ``## heading``, ``- item``, ``**bold**`` and paragraphs, the same small format as the bot and the cabinet.
struct DocumentText: View {
    let text: String
    let theme: LayoutTheme

    private func rich(_ line: String) -> Text {
        var out = Text("")
        var rest = Substring(line)
        while let start = rest.range(of: "**"), let end = rest[start.upperBound...].range(of: "**") {
            out = out + Text(String(rest[..<start.lowerBound])).foregroundColor(theme.text)
            out = out + Text(String(rest[start.upperBound..<end.lowerBound])).bold().foregroundColor(theme.accent2)
            rest = rest[end.upperBound...]
        }
        return out + Text(String(rest)).foregroundColor(theme.text)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(text.components(separatedBy: "\n").enumerated()), id: \.offset) { _, raw in
                let line = raw.trimmingCharacters(in: .whitespaces)
                if line.isEmpty { Spacer().frame(height: 4) }
                else if line.hasPrefix("## ") { rich(String(line.dropFirst(3))).font(.system(size: 18, weight: .bold)) }
                else if line.hasPrefix("- ") { rich("•  " + line.dropFirst(2)).font(.system(size: 15)) }
                else { rich(line).font(.system(size: 15)) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct DocumentView: View {
    let layout: AppLayout
    let base: String
    let doc: [String: Any]
    let onBack: () -> Void
    let onLink: (String) -> Void
    @State private var open: Set<Int> = []

    var body: some View {
        let theme = layout.theme
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Button(action: onBack) { Image(systemName: "chevron.left").font(.system(size: 20, weight: .semibold)).foregroundStyle(theme.text) }
                    .accessibilityLabel("Назад")
                Text(jsonText(doc["title"])).font(.system(size: 26, weight: .bold)).foregroundStyle(theme.text)
                let banner = jsonText(doc["banner"])
                if !banner.isEmpty { SectionBannerView(base: base, banner: LayoutBanner(url: banner, link: ""), theme: theme, onLink: onLink) }
                let text = jsonText(doc["body"])
                if !text.isEmpty { CardView(theme: theme) { DocumentText(text: text, theme: theme) } }
                ForEach(Array((doc["items"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { i, item in
                    Button {
                        if open.contains(i) { open.remove(i) } else { open.insert(i) }
                    } label: {
                        CardView(theme: theme) {
                            HStack {
                                Text(jsonText(item["question"])).fontWeight(.bold).foregroundStyle(theme.text).multilineTextAlignment(.leading)
                                Spacer()
                                Image(systemName: open.contains(i) ? "minus" : "plus").foregroundStyle(theme.accent)
                            }
                            if open.contains(i) { DocumentText(text: jsonText(item["answer"]), theme: theme) }
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 18).padding(.vertical, 12).padding(.bottom, 24)
        }
        .background(theme.background.ignoresSafeArea())
    }
}
