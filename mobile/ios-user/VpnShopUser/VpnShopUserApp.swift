import Network
import AuthenticationServices
import CryptoKit
import DeviceCheck
import Security
import SwiftUI
import UIKit
import UserNotifications

@main
struct VpnShopUserApp: App {
    @UIApplicationDelegateAdaptor(PushAppDelegate.self) private var pushDelegate
    var body: some Scene {
        WindowGroup {
            UserRootView()
        }
    }
}

let localHttpHosts: Set<String> = ["localhost", "127.0.0.1", "10.0.2.2"]

func pkceVerifier() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw URLError(.unknown) }
    return Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
}
func pkceChallenge(_ verifier: String) -> String {
    Data(SHA256.hash(data: Data(verifier.utf8))).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
}


func subscriptionApps(_ url: String) -> [(String, String)] {
    guard url.hasPrefix("https://"), !url.contains(where: { $0.isWhitespace }) else { return [] }
    var allowed = CharacterSet.alphanumerics
    allowed.insert(charactersIn: "-._~")
    let encoded = url.addingPercentEncoding(withAllowedCharacters: allowed) ?? ""
    return [("Happ", "happ://add/\(encoded)"), ("v2rayNG", "v2rayng://install-sub?url=\(encoded)"), ("Streisand", "streisand://import/\(encoded)")]
}

func normalizeBase(_ raw: String) throws -> String {
    let value = raw.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    guard let url = URL(string: value), let host = url.host?.lowercased(), url.user == nil, !value.contains(where: \.isWhitespace) else {
        throw URLError(.badURL)
    }
    if url.scheme == "https" { return value }
    if url.scheme == "http", localHttpHosts.contains(host) { return value }
    throw URLError(.badURL)
}

/// Shop address baked into the build (Info.plist CorgiShopURL ← CORGI_SHOP_URL); "" when not set.
let bakedShopURL: String = {
    let raw = (Bundle.main.object(forInfoDictionaryKey: "CorgiShopURL") as? String) ?? ""
    guard !raw.isEmpty, !raw.hasPrefix("$("), let value = try? normalizeBase(raw), value.hasPrefix("https://") else { return "" }
    return value
}()

/// Certificate pinning (Info.plist CorgiPins ← CORGI_PINS: base64 SHA-256 of SPKI, comma separated)
/// for the baked shop host, and the DeviceCheck token of sign-ins when the shop asks for it.
enum CorgiTrust {
    static let pins: Set<String> = Set(((Bundle.main.object(forInfoDictionaryKey: "CorgiPins") as? String) ?? "")
        .split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty && !$0.hasPrefix("$(") })
    static let pinnedHost: String = URL(string: bakedShopURL)?.host?.lowercased() ?? ""
    static var pinning: Bool { !pins.isEmpty && !pinnedHost.isEmpty }

    // ASN.1 SubjectPublicKeyInfo headers: the key bytes iOS returns lack them.
    private static let rsa2048: [UInt8] = [0x30, 0x82, 0x01, 0x22, 0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00, 0x03, 0x82, 0x01, 0x0f, 0x00]
    private static let rsa4096: [UInt8] = [0x30, 0x82, 0x02, 0x22, 0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00, 0x03, 0x82, 0x02, 0x0f, 0x00]
    private static let ec256: [UInt8] = [0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01, 0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00]
    private static let ec384: [UInt8] = [0x30, 0x76, 0x30, 0x10, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01, 0x06, 0x05, 0x2b, 0x81, 0x04, 0x00, 0x22, 0x03, 0x62, 0x00]

    static func spkiHash(_ certificate: SecCertificate) -> String? {
        guard let key = SecCertificateCopyKey(certificate), let raw = SecKeyCopyExternalRepresentation(key, nil) as Data?,
              let attributes = SecKeyCopyAttributes(key) as? [String: Any] else { return nil }
        let type = attributes[kSecAttrKeyType as String] as? String
        let bits = attributes[kSecAttrKeySizeInBits as String] as? Int ?? 0
        let header: [UInt8]
        if type == (kSecAttrKeyTypeRSA as String) { header = bits == 4096 ? rsa4096 : rsa2048 }
        else if bits == 384 { header = ec384 } else { header = ec256 }
        return Data(SHA256.hash(data: Data(header) + raw)).base64EncodedString()
    }

    static func accepts(_ trust: SecTrust) -> Bool {
        guard SecTrustEvaluateWithError(trust, nil) else { return false }
        let chain = (SecTrustCopyCertificateChain(trust) as? [SecCertificate]) ?? []
        return chain.compactMap(spkiHash).contains { pins.contains($0) }
    }

    /// DeviceCheck token for the native token exchange; empty when the shop does not ask.
    static func integrityHeaders(_ client: ShopClient) -> [String: String] {
        guard let challenge = try? client.call("GET", "/api/mobile/integrity/challenge") as? [String: Any],
              (challenge["mode"] as? String ?? "off") != "off", DCDevice.current.isSupported else { return [:] }
        let semaphore = DispatchSemaphore(value: 0)
        var token = ""
        DCDevice.current.generateToken { data, _ in token = data?.base64EncodedString() ?? ""; semaphore.signal() }
        _ = semaphore.wait(timeout: .now() + 15)
        return token.isEmpty ? [:] : ["X-Shop-Integrity": token, "X-Shop-Integrity-Nonce": jsonText(challenge["nonce"])]
    }
}

/// corgi://login?base=…&code=… — a one-use sign-in link (backend/app/app_login.py).
/// Order of corgi://payment?order=… (back from the payment page, backend/app/app_login.py).
func paymentOrder(_ url: URL) -> String? {
    guard url.scheme == "corgi", url.host == "payment",
          let order = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "order" })?.value,
          order.range(of: "^[A-Za-z0-9_.:-]{6,128}$", options: .regularExpression) != nil else { return nil }
    return order
}

struct LoginLink: Equatable {
    let base: String
    let code: String

    static func parse(_ url: URL) -> LoginLink? {
        guard url.scheme == "corgi", url.host == "login",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems else { return nil }
        let code = items.first { $0.name == "code" }?.value ?? ""
        guard code.range(of: "^[A-Za-z0-9_-]{20,128}$", options: .regularExpression) != nil else { return nil }
        let base = (try? normalizeBase(items.first { $0.name == "base" }?.value ?? "")) ?? ""
        return LoginLink(base: base, code: code)
    }

    /// The shop the link may sign in to: a baked address wins, a foreign one is refused.
    static func target(_ link: LoginLink, baked: String, current: String) -> String? {
        if !baked.isEmpty { return link.base.isEmpty || link.base == baked ? baked : nil }
        if !link.base.isEmpty { return link.base }
        return current.isEmpty ? nil : current
    }
}

/// Anonymous app statistics («Приложения: аналитика», backend/app/app_growth.py): a random
/// installation id (never a device identifier), platform, app version, event and screen.
enum CorgiAnalytics {
    static var enabled = true
    private static var queue: [[String: String]] = []
    private static var lastFlush = Date.distantPast
    private static let lock = NSLock()

    static var installId: String {
        if let id = UserDefaults.standard.string(forKey: "install_id") { return id }
        let id = UUID().uuidString
        UserDefaults.standard.set(id, forKey: "install_id")
        UserDefaults.standard.set(false, forKey: "install_reported")
        return id
    }

    static func install(base: String) {
        _ = installId
        if UserDefaults.standard.bool(forKey: "install_reported") { return }
        UserDefaults.standard.set(true, forKey: "install_reported")
        track(base: base, token: "", event: "install")
    }

    static func track(base: String, token: String, event: String, screen: String = "") {
        guard enabled, !base.isEmpty, let url = URL(string: base + "/api/mobile/events") else { return }
        var row = ["event": event]
        if !screen.isEmpty { row["screen"] = String(screen.lowercased().filter { $0.isLetter || $0.isNumber || $0 == "_" || $0 == "-" }.prefix(32)) }
        lock.lock()
        queue.append(row)
        // Important steps of the funnel leave at once; screens wait for ten or half a minute.
        if event == "screen" && queue.count < 10 && Date().timeIntervalSince(lastFlush) < 30 { lock.unlock(); return }
        let batch = queue
        queue = []
        lastFlush = Date()
        lock.unlock()
        let version = (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? ""
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("ios-user", forHTTPHeaderField: "X-Shop-Client")
        request.setValue("CorgiLusi-iOS-User/3.3.0", forHTTPHeaderField: "User-Agent")
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["install_id": installId, "platform": "ios", "app_version": version, "events": batch])
        URLSession.shared.dataTask(with: request) { data, _, _ in
            // Statistics never get in the way: a lost batch is not retried.
            if let data, let answer = try? JSONSerialization.jsonObject(with: data) as? [String: Any], answer["enabled"] as? Bool == false { enabled = false }
        }.resume()
    }
}

func jsonInt(_ value: Any?) -> Int? {
    if value == nil || value is NSNull { return nil }
    if let number = value as? Int { return number }
    if let number = value as? NSNumber { return number.intValue }
    if let text = value as? String { return Int(text) }
    return nil
}

func jsonBool(_ value: Any?) -> Bool {
    if let flag = value as? Bool { return flag }
    if let number = value as? NSNumber { return number.boolValue }
    return false
}

func jsonText(_ value: Any?) -> String {
    if value == nil || value is NSNull { return "" }
    if let text = value as? String { return text }
    if let number = value as? NSNumber { return number.stringValue }
    return ""
}

func safeMediaPath(_ path: String) -> String? {
    guard path.hasPrefix("/media/"), !path.contains(".."), !path.contains("://"), !path.contains("\\"), !path.contains("?"), !path.contains("#") else { return nil }
    let name = String(path.dropFirst("/media/".count))
    if name.isEmpty || name.contains("/") { return nil }
    return path
}

func publicNode(_ row: [String: Any]) -> [String: Any] {
    let status = (row["status"] as? String) ?? "unknown"
    let safe = ["online", "offline", "disabled", "unknown"].contains(status) ? status : "unknown"
    var name = (row["name"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    if name.isEmpty { name = "node" }
    if name.contains("://") || (name.filter { $0 == "." }.count >= 3 && name.contains(where: \.isNumber)) { name = "node" }
    return ["name": name, "country": row["country"] as? String ?? "", "status": safe, "users_online": jsonInt(row["users_online"]) ?? 0]
}

final class ShopClient: NSObject, URLSessionTaskDelegate {
    let base: String
    let token: String
    let lang: String
    private lazy var session: URLSession = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: nil)

    init(base: String, token: String, lang: String) {
        self.base = base
        self.token = token
        self.lang = lang
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }

    /// Certificate pinning of the baked shop host (CorgiTrust); other hosts use the system trust.
    func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust, CorgiTrust.pinning,
              challenge.protectionSpace.host.lowercased() == CorgiTrust.pinnedHost else {
            completionHandler(.performDefaultHandling, nil); return
        }
        if CorgiTrust.accepts(trust) { completionHandler(.useCredential, URLCredential(trust: trust)) }
        else { completionHandler(.cancelAuthenticationChallenge, nil) }
    }

    func call(_ method: String, _ path: String, body: [String: Any]? = nil, idempotency: String? = nil, headers: [String: String] = [:]) throws -> Any {
        let origin = CorgiMirrors.resolve(base)
        do {
            return try send(origin, method, path, body: body, idempotency: idempotency, headers: headers)
        } catch let error as URLError {
            // Blocked or unreachable address: move to a signed reserve address. A request is repeated there
            // only when it surely never reached the server (or is a GET), so nothing is paid or sent twice.
            guard let next = CorgiMirrors.failover(home: base, failed: origin) else { throw error }
            let unsent: Set<URLError.Code> = [.cannotFindHost, .cannotConnectToHost, .dnsLookupFailed, .secureConnectionFailed, .serverCertificateUntrusted]
            if method != "GET" && !unsent.contains(error.code) { throw error }
            return try send(next, method, path, body: body, idempotency: idempotency, headers: headers)
        }
    }

    private func send(_ origin: String, _ method: String, _ path: String, body: [String: Any]?, idempotency: String?, headers: [String: String]) throws -> Any {
        // Every sign-in that issues a session (password or passkey) is bound to a fresh PKCE verifier.
        let verifier: String? = try (["/api/auth/login", "/api/auth/register", "/api/admin/auth/login", "/api/auth/passkeys/login/verify", "/api/auth/mobile/code"].contains(path) ? pkceVerifier() : nil)
        guard let url = URL(string: origin + path) else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        if let verifier { request.setValue(pkceChallenge(verifier), forHTTPHeaderField: "X-Shop-Code-Challenge") }
        request.httpMethod = method
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(lang, forHTTPHeaderField: "Accept-Language")
        request.setValue("CorgiLusi-iOS-User/3.3.0", forHTTPHeaderField: "User-Agent")
        // Historical compatibility marker: CorgiLusi-iOS-User/2.9.0
        request.setValue("ios-user", forHTTPHeaderField: "X-Shop-Client")


        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let idempotency { request.setValue(idempotency, forHTTPHeaderField: "Idempotency-Key") }
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let semaphore = DispatchSemaphore(value: 0)
        var payload = Data()
        var status = 0
        var failure: Error?
        session.dataTask(with: request) { data, response, error in
            payload = data ?? Data()
            status = (response as? HTTPURLResponse)?.statusCode ?? 0
            failure = error
            semaphore.signal()
        }.resume()
        semaphore.wait()
        if let failure { throw failure }
        // /api/me/sync answers 304 when the account did not change.
        if status == 304 { return [String: Any]() }
        if !(200...299).contains(status) { throw NSError(domain: "shop", code: status, userInfo: [NSLocalizedDescriptionKey: detailOf(payload, status)]) }
        if payload.isEmpty { return [String: Any]() }
        let decoded = try JSONSerialization.jsonObject(with: payload)
        if let verifier, var result = decoded as? [String: Any], let code = result["authorization_code"] as? String {
            let exchanged = try call("POST", "/api/auth/mobile/token", body: ["code": code, "code_verifier": verifier], headers: CorgiTrust.integrityHeaders(self)) as? [String: Any]
            result.removeValue(forKey: "authorization_code")
            result["access_token"] = exchanged?["access_token"]
            result["token_type"] = "bearer"
            return result
        }
        return decoded
    }

    func bytes(_ path: String) throws -> Data {
        guard let safe = safeMediaPath(path), let url = URL(string: CorgiMirrors.resolve(base) + safe) else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        request.timeoutInterval = 15
        request.setValue("image/png,image/jpeg,image/webp", forHTTPHeaderField: "Accept")
        let semaphore = DispatchSemaphore(value: 0)
        var payload = Data()
        var status = 0
        var failure: Error?
        session.dataTask(with: request) { data, response, error in
            payload = data ?? Data()
            status = (response as? HTTPURLResponse)?.statusCode ?? 0
            failure = error
            semaphore.signal()
        }.resume()
        semaphore.wait()
        if let failure { throw failure }
        if !(200...299).contains(status) || payload.count > 2 * 1024 * 1024 { throw URLError(.badServerResponse) }
        return payload
    }
}

private func detailOf(_ payload: Data, _ status: Int) -> String {
    let json = (try? JSONSerialization.jsonObject(with: payload)) as? [String: Any]
    if let detail = json?["detail"] as? String, !detail.isEmpty { return String(detail.prefix(300)) }
    if let list = json?["detail"] as? [[String: Any]], let msg = list.first?["msg"] as? String { return String(msg.prefix(300)) }
    return "HTTP \(status)"
}

func loadStrings(_ lang: String) -> [String: String] {
    guard let url = Bundle.main.url(forResource: "l10n", withExtension: "json"),
          let data = try? Data(contentsOf: url),
          let root = try? JSONSerialization.jsonObject(with: data) as? [String: [String: String]],
          let table = root[lang] else { return [:] }
    return table
}


/// Device-only Keychain storage; plaintext UserDefaults sessions are never reused.
enum SessionKeychain {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: (Bundle.main.bundleIdentifier ?? "shop.session") + ".session.v2",
         kSecAttrAccount as String: "session"]
    }
    static func clear() { SecItemDelete(query as CFDictionary) }
    static func load(baseKey: String, legacyKey: String) -> String {
        UserDefaults.standard.removeObject(forKey: legacyKey)
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(lookup as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let stored = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              stored["base"] == UserDefaults.standard.string(forKey: baseKey) else { return "" }
        return stored["token"] ?? ""
    }
    static func save(_ token: String, base: String) throws {
        let data = try JSONSerialization.data(withJSONObject: ["token": token, "base": base])
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil)
        }
        guard status == errSecSuccess else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
    }
}


// MARK: - Native push (APNs)

enum PushError: Error { case denied }

/// Opt-in APNs registration. The token is bound on the server to the signed-in session and
/// revoked on sign-out, so a shared iPhone never receives another account's notifications.
final class PushCenter: ObservableObject {
    static let shared = PushCenter()
    static let enabledKey = "push_enabled"
    static let tokenKey = "push_token"
    @Published var openNotifications = false
    /// Section a tapped push or one of its buttons opens («Приложения: стиль push-уведомлений»).
    @Published var openSection: String?
    @Published private(set) var latestToken: String?
    private var pending: ((Result<String, Error>) -> Void)?

    var enabled: Bool { UserDefaults.standard.bool(forKey: Self.enabledKey) }

    /// Asks for permission and returns the APNs device token on the main queue.
    func requestToken(_ completion: @escaping (Result<String, Error>) -> Void) {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            DispatchQueue.main.async {
                if let error { completion(.failure(error)); return }
                guard granted else { completion(.failure(PushError.denied)); return }
                self.pending = completion
                UIApplication.shared.registerForRemoteNotifications()
            }
        }
    }

    func received(_ deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        latestToken = hex
        pending?(.success(hex))
        pending = nil
    }

    func failed(_ error: Error) {
        pending?(.failure(error))
        pending = nil
    }

    /// Blocking network call; run off the main queue.
    static func register(base: String, session: String, lang: String, token: String) throws -> [String: Any] {
        var body: [String: Any] = [
            "platform": "ios",
            "token": token,
            "app_version": String((Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "").prefix(32)),
            "locale": String(lang.prefix(8)),
        ]
        if let previous = UserDefaults.standard.string(forKey: tokenKey), previous != token { body["replaces"] = previous }
        let response = try ShopClient(base: base, token: session, lang: lang).call("POST", "/api/me/push/devices", body: body) as? [String: Any] ?? [:]
        UserDefaults.standard.set(token, forKey: tokenKey)
        UserDefaults.standard.set(true, forKey: enabledKey)
        return response
    }

    /// Buttons of every push type as notification categories (GET /api/mobile/push-style).
    /// Blocking network call; run off the main queue. Failures keep the previous categories.
    static func registerCategories(base: String, lang: String) {
        guard let style = try? ShopClient(base: base, token: "", lang: lang).call("GET", "/api/mobile/push-style") as? [String: Any],
              let categories = style["categories"] as? [String: Any] else { return }
        var set = Set<UNNotificationCategory>()
        for (kind, raw) in categories {
            let buttons = (raw as? [[String: Any]] ?? []).prefix(2)
            let actions = buttons.compactMap { button -> UNNotificationAction? in
                let label = jsonText(button["label"]), section = jsonText(button["section"])
                guard !label.isEmpty, section.range(of: "^[a-z][a-z0-9_-]{0,31}$", options: .regularExpression) != nil else { return nil }
                return UNNotificationAction(identifier: "open:\(section)", title: String(label.prefix(24)), options: [.foreground])
            }
            set.insert(UNNotificationCategory(identifier: kind, actions: actions, intentIdentifiers: [], options: []))
        }
        UNUserNotificationCenter.current().setNotificationCategories(set)
    }

    /// Blocking network call that never throws: revoke on the server, then stop APNs locally.
    static func unregister(base: String, session: String, lang: String) {
        let token = UserDefaults.standard.string(forKey: tokenKey)
        UserDefaults.standard.removeObject(forKey: tokenKey)
        UserDefaults.standard.set(false, forKey: enabledKey)
        if let token, !base.isEmpty, !session.isEmpty {
            _ = try? ShopClient(base: base, token: session, lang: lang).call("POST", "/api/me/push/devices/unregister", body: ["token": token])
        }
        DispatchQueue.main.async { UIApplication.shared.unregisterForRemoteNotifications() }
    }
}

final class PushAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        // APNs may rotate the token; fetch the current one so the next refresh re-binds it.
        if PushCenter.shared.enabled { application.registerForRemoteNotifications() }
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        PushCenter.shared.received(deviceToken)
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        PushCenter.shared.failed(error)
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        let action = response.actionIdentifier
        let info = response.notification.request.content.userInfo
        var section = action.hasPrefix("open:") ? String(action.dropFirst(5)) : (info["section"] as? String ?? "")
        if section.range(of: "^[a-z][a-z0-9_-]{0,31}$", options: .regularExpression) == nil { section = "" }
        DispatchQueue.main.async {
            if section.isEmpty { PushCenter.shared.openNotifications = true } else { PushCenter.shared.openSection = section }
        }
        completionHandler()
    }
}


// MARK: - Passkeys

func base64url(_ data: Data) -> String {
    data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
}

func base64urlData(_ text: String) -> Data? {
    var value = text.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
    while value.count % 4 != 0 { value += "=" }
    return Data(base64Encoded: value)
}

enum PasskeyError: LocalizedError {
    case cancelled, noPasskey, invalidOptions, failed(String)
    var errorDescription: String? {
        switch self {
        case .cancelled: return "cancelled"
        case .noPasskey: return "no passkey"
        case .invalidOptions: return "invalid passkey options"
        case .failed(let message): return message
        }
    }
}

/// One AuthenticationServices ceremony. The cabinet domain is the relying party:
/// it publishes apple-app-site-association with `webcredentials` for this app, the
/// app lists `webcredentials:<cabinet domain>` in its associated domains, and iOS
/// signs with the cabinet origin that the server accepts.
/// `run` blocks the calling background thread until the system sheet finishes.
final class PasskeyCeremony: NSObject, ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    private var result: Result<[String: Any], Error> = .failure(PasskeyError.cancelled)
    private let done = DispatchSemaphore(value: 0)
    private var controller: ASAuthorizationController?

    static func assertion(options: [String: Any]) throws -> [String: Any] {
        guard let rpId = options["rpId"] as? String, let challenge = base64urlData(options["challenge"] as? String ?? "") else {
            throw PasskeyError.invalidOptions
        }
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpId)
        let request = provider.createCredentialAssertionRequest(challenge: challenge)
        request.userVerificationPreference = .required
        let allowed = (options["allowCredentials"] as? [[String: Any]] ?? []).compactMap { base64urlData($0["id"] as? String ?? "") }
        if !allowed.isEmpty { request.allowedCredentials = allowed.map { ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: $0) } }
        return try PasskeyCeremony().run(request)
    }

    static func registration(options: [String: Any]) throws -> [String: Any] {
        guard let rp = options["rp"] as? [String: Any], let rpId = rp["id"] as? String,
              let user = options["user"] as? [String: Any], let userID = base64urlData(user["id"] as? String ?? ""),
              let challenge = base64urlData(options["challenge"] as? String ?? "") else {
            throw PasskeyError.invalidOptions
        }
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpId)
        let request = provider.createCredentialRegistrationRequest(challenge: challenge, name: user["name"] as? String ?? "VPN Shop", userID: userID)
        request.userVerificationPreference = .required
        return try PasskeyCeremony().run(request)
    }

    private func run(_ request: ASAuthorizationRequest) throws -> [String: Any] {
        DispatchQueue.main.async {
            let controller = ASAuthorizationController(authorizationRequests: [request])
            controller.delegate = self
            controller.presentationContextProvider = self
            self.controller = controller  // kept alive until the delegate answers
            controller.performRequests()
        }
        done.wait()
        return try result.get()
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        return scenes.flatMap { $0.windows }.first { $0.isKeyWindow } ?? ASPresentationAnchor()
    }

    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization) {
        if let assertion = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialAssertion {
            let id = base64url(assertion.credentialID)
            result = .success(["id": id, "rawId": id, "type": "public-key", "response": [
                "clientDataJSON": base64url(assertion.rawClientDataJSON),
                "authenticatorData": base64url(assertion.rawAuthenticatorData),
                "signature": base64url(assertion.signature),
                "userHandle": base64url(assertion.userID),
            ]])
        } else if let registration = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialRegistration,
                  let attestation = registration.rawAttestationObject {
            let id = base64url(registration.credentialID)
            result = .success(["id": id, "rawId": id, "type": "public-key", "response": [
                "clientDataJSON": base64url(registration.rawClientDataJSON),
                "attestationObject": base64url(attestation),
            ]])
        } else {
            result = .failure(PasskeyError.failed("passkey"))
        }
        done.signal()
    }

    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        let code = (error as? ASAuthorizationError)?.code
        result = .failure(code == .canceled ? PasskeyError.cancelled : PasskeyError.failed(error.localizedDescription))
        done.signal()
    }
}

/// Server side of the passkey flows; the challenge binding stays in memory for one ceremony.
enum ShopPasskeys {
    static func signIn(base: String, lang: String) throws -> String {
        let api = ShopClient(base: base, token: "", lang: lang)
        guard let start = try api.call("POST", "/api/auth/passkeys/login/options", body: [:]) as? [String: Any],
              let options = start["options"] as? [String: Any], let ticket = start["ticket"] as? String,
              let binding = start["binding"] as? String else { throw PasskeyError.invalidOptions }
        let credential = try PasskeyCeremony.assertion(options: options)
        let result = try api.call("POST", "/api/auth/passkeys/login/verify", body: ["ticket": ticket, "credential": credential],
                                  headers: ["X-Shop-Passkey-Binding": binding]) as? [String: Any]
        guard let token = result?["access_token"] as? String, !token.isEmpty else { throw PasskeyError.failed("HTTP") }
        return token
    }

    static func register(base: String, session: String, lang: String, password: String, name: String) throws {
        let api = ShopClient(base: base, token: session, lang: lang)
        var body: [String: Any] = ["name": name]
        if !password.isEmpty { body["password"] = password }
        guard let start = try api.call("POST", "/api/auth/passkeys/registration/options", body: body) as? [String: Any],
              let options = start["options"] as? [String: Any], let ticket = start["ticket"] as? String,
              let binding = start["binding"] as? String else { throw PasskeyError.invalidOptions }
        let credential = try PasskeyCeremony.registration(options: options)
        _ = try api.call("POST", "/api/auth/passkeys/registration/verify", body: ["ticket": ticket, "credential": credential],
                         headers: ["X-Shop-Passkey-Binding": binding])
    }

    static func list(base: String, session: String, lang: String) throws -> [[String: Any]] {
        try ShopClient(base: base, token: session, lang: lang).call("GET", "/api/auth/passkeys") as? [[String: Any]] ?? []
    }

    static func delete(base: String, session: String, lang: String, id: Int, password: String) throws {
        var body: [String: Any] = [:]
        if !password.isEmpty { body["password"] = password }
        _ = try ShopClient(base: base, token: session, lang: lang).call("POST", "/api/auth/passkeys/\(id)/delete", body: body)
    }
}


/// Domain rotation: when the shop's API address is blocked the app moves to a reserve address by itself.
///
/// The shop publishes a signed list (GET /api/public/mirrors, ECDSA P-256). The app remembers the shop's key
/// from the address the customer signed in to (trust on first use) and from then on accepts reserve addresses
/// — from the shop or from bootstrap copies such as a GitHub Gist — only with a valid signature. The session
/// token stays bound to the home address: only the network origin changes.
enum CorgiMirrors {
    private static let store = UserDefaults(suiteName: "corgi_mirrors") ?? .standard
    private static let lock = NSLock()
    private static var lastFailover = Date.distantPast

    private static func get(_ home: String, _ name: String) -> String { store.string(forKey: "\(name)|\(home)") ?? "" }
    private static func put(_ home: String, _ values: [String: String]) { for (name, value) in values { store.set(value, forKey: "\(name)|\(home)") } }

    /// Origin to send requests for `home` to: the home address or the reserve one in use.
    static func resolve(_ home: String) -> String { let active = get(home, "active"); return active.isEmpty ? home : active }

    /// Verified payload of a signed document, or nil. `expected` is the remembered shop key, if any.
    static func verify(_ document: [String: Any], expected: String?) -> [String: Any]? {
        guard let keyText = document["key"] as? String, let payloadText = document["payload"] as? String,
              let signatureText = document["signature"] as? String,
              expected == nil || expected == "" || expected == keyText,
              let keyData = Data(base64Encoded: keyText), let signatureData = Data(base64Encoded: signatureText),
              let key = try? P256.Signing.PublicKey(derRepresentation: keyData),
              let signature = try? P256.Signing.ECDSASignature(derRepresentation: signatureData),
              key.isValidSignature(signature, for: Data(payloadText.utf8)),
              let payload = (try? JSONSerialization.jsonObject(with: Data(payloadText.utf8))) as? [String: Any],
              let expires = (payload["expires_at"] as? String).flatMap({ ISO8601DateFormatter().date(from: $0) }), expires > Date() else { return nil }
        return payload
    }

    private static func fetch(_ url: String) -> [String: Any]? {
        guard let target = URL(string: url) else { return nil }
        var request = URLRequest(url: target)
        request.timeoutInterval = 7
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let semaphore = DispatchSemaphore(value: 0)
        var result: [String: Any]?
        URLSession(configuration: .ephemeral).dataTask(with: request) { data, response, _ in
            if let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let data, data.count < 64 * 1024 {
                result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            }
            semaphore.signal()
        }.resume()
        semaphore.wait()
        return result
    }

    private static func remember(_ home: String, _ payload: [String: Any]) {
        UserDefaults(suiteName: CorgiXray.appGroup)?.set(payload["direct"] as? [String] ?? [], forKey: CorgiXray.keyDirectExtra)
        let list = { (key: String) -> String in
            String(data: (try? JSONSerialization.data(withJSONObject: payload[key] as? [String] ?? [])) ?? Data("[]".utf8), encoding: .utf8) ?? "[]"
        }
        put(home, ["mirrors": list("mirrors"), "bootstrap": list("bootstrap"), "shop": payload["shop"] as? String ?? ""])
    }

    private static func list(_ home: String, _ name: String) -> [String] {
        (try? JSONSerialization.jsonObject(with: Data(get(home, name).utf8))) as? [String] ?? []
    }

    /// After a successful answer: refresh the reserve list and return home once home works again.
    static func learn(_ home: String) {
        if home.isEmpty { return }
        let known = get(home, "key")
        if let doc = fetch(home + "/api/public/mirrors") {
            guard let payload = verify(doc, expected: known) else { return }
            if known.isEmpty, let key = doc["key"] as? String { put(home, ["key": key]) }
            remember(home, payload)
            put(home, ["active": ""])
            return
        }
        let active = get(home, "active")
        if !active.isEmpty, !known.isEmpty, let doc = fetch(active + "/api/public/mirrors"), let payload = verify(doc, expected: known) { remember(home, payload) }
    }

    /// The current origin does not answer: find a reserve address that proves it is this shop.
    static func failover(home: String, failed: String) -> String? {
        lock.lock(); defer { lock.unlock() }
        let known = get(home, "key")
        if known.isEmpty { return nil }
        let current = resolve(home)
        if current != failed { return current }
        if Date().timeIntervalSince(lastFailover) < 30 { return nil }
        lastFailover = Date()
        var candidates = list(home, "mirrors").map { $0.hasSuffix("/") ? String($0.dropLast()) : $0 }
        candidates.append(home)
        for source in list(home, "bootstrap") {
            guard let doc = fetch(source), let payload = verify(doc, expected: known) else { continue }
            remember(home, payload)
            candidates.append(contentsOf: payload["mirrors"] as? [String] ?? [])
        }
        var seen = Set<String>()
        for candidate in candidates where candidate != failed && candidate.hasPrefix("https://") && seen.insert(candidate).inserted {
            guard let doc = fetch(candidate + "/api/public/mirrors"), let payload = verify(doc, expected: known) else { continue }
            remember(home, payload)
            put(home, ["active": candidate == home ? "" : candidate])
            return candidate
        }
        return nil
    }
}

/// «Не работает VPN»: what the phone sees from its own network, sent to POST /api/me/diagnostics with the customer's
/// words; the shop adds subscription, device limit and node state and answers with the likely cause.
/// Blocking, call it off the main thread (inside `work`).
enum CorgiDiagnostics {
    private static func timed(_ name: String, _ target: String, _ block: () throws -> String) -> [String: Any] {
        let started = Date()
        do {
            let detail = try block()
            return ["name": name, "target": String(target.prefix(200)), "ok": true, "ms": Int(Date().timeIntervalSince(started) * 1000), "detail": String(detail.prefix(300))]
        } catch {
            return ["name": name, "target": String(target.prefix(200)), "ok": false, "detail": String(String(describing: error).prefix(300))]
        }
    }

    private struct Failed: Error, CustomStringConvertible { let description: String }

    private static func get(_ url: String, _ agent: String) throws -> String {
        guard let target = URL(string: url) else { throw Failed(description: "bad url") }
        var request = URLRequest(url: target, timeoutInterval: 8)
        request.setValue(agent, forHTTPHeaderField: "User-Agent")
        let done = DispatchSemaphore(value: 0)
        var result: Result<String, Error> = .failure(Failed(description: "timeout"))
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error { result = .failure(error) }
            else if let code = (response as? HTTPURLResponse)?.statusCode, !(200...299).contains(code) { result = .failure(Failed(description: "HTTP \(code)")) }
            else { result = .success(String(data: data ?? Data(), encoding: .utf8) ?? "") }
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 10)
        return try result.get()
    }

    private static func resolveHost(_ host: String) throws -> String {
        var hints = addrinfo(ai_flags: 0, ai_family: AF_UNSPEC, ai_socktype: SOCK_STREAM, ai_protocol: 0, ai_addrlen: 0, ai_canonname: nil, ai_addr: nil, ai_next: nil)
        var list: UnsafeMutablePointer<addrinfo>?
        let status = getaddrinfo(host, nil, &hints, &list)
        defer { if list != nil { freeaddrinfo(list) } }
        if status != 0 { throw Failed(description: String(cString: gai_strerror(status))) }
        return "ok"
    }

    private static func connect(_ host: String, _ port: Int) throws -> String {
        guard let endpointPort = NWEndpoint.Port(rawValue: UInt16(port)) else { throw Failed(description: "bad port") }
        let connection = NWConnection(host: NWEndpoint.Host(host), port: endpointPort, using: .tcp)
        let done = DispatchSemaphore(value: 0)
        var outcome: String?
        connection.stateUpdateHandler = { state in
            switch state {
            case .ready: outcome = "tcp"; done.signal()
            case .failed(let error), .waiting(let error): if outcome == nil { outcome = "!\(error)" }; done.signal()
            default: break
            }
        }
        connection.start(queue: .global())
        _ = done.wait(timeout: .now() + 5)
        connection.cancel()
        guard let outcome, !outcome.hasPrefix("!") else { throw Failed(description: outcome.map { String($0.dropFirst()) } ?? "timeout") }
        return outcome
    }

    /// host:port of every server (vless/vmess: vnext, trojan/shadowsocks: servers).
    private static func endpoints(_ body: String) -> [(String, Int)] {
        var seen = Set<String>(); var out: [(String, Int)] = []
        for server in CorgiXray.parseAll(body) {
            let settings = server.outbound["settings"] as? [String: Any] ?? [:]
            let first = ((settings["vnext"] ?? settings["servers"]) as? [[String: Any]])?.first ?? [:]
            guard let host = first["address"] as? String, let port = first["port"] as? Int, !host.isEmpty, (1...65535).contains(port) else { continue }
            if seen.insert("\(host):\(port)").inserted { out.append((host, port)) }
            if out.count >= 12 { break }
        }
        return out
    }

    static func run(base: String, subscription: String) -> [[String: Any]] {
        var checks: [[String: Any]] = []
        let origin = CorgiMirrors.resolve(base)
        let host = URL(string: origin)?.host ?? ""
        checks.append(timed("dns", host) { try resolveHost(host) })
        checks.append(timed("api", "\(origin)/health/live") { _ = try get("\(origin)/health/live", "CorgiLusi-iOS-User/3.3.0"); return "ok" })
        var body = ""
        checks.append(timed("subscription", "") { body = try get(subscription, "v2rayNG/1.10.0 CorgiLusi"); return "\(CorgiXray.parseAll(body).count) серверов" })
        for (address, port) in body.isEmpty ? [] : endpoints(body) {
            checks.append(timed("server", "\(address):\(port)") { try connect(address, port) })
        }
        return checks
    }
}
