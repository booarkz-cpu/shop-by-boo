import CryptoKit
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

    func call(_ method: String, _ path: String, body: [String: Any]? = nil, idempotency: String? = nil) throws -> Any {
        let verifier: String? = try (["/api/auth/login", "/api/auth/register", "/api/admin/auth/login"].contains(path) ? pkceVerifier() : nil)
        var request = URLRequest(url: URL(string: base + path)!)
        if let verifier { request.setValue(pkceChallenge(verifier), forHTTPHeaderField: "X-Shop-Code-Challenge") }
        request.httpMethod = method
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(lang, forHTTPHeaderField: "Accept-Language")
        request.setValue("CorgiLusi-iOS-User/2.15.0", forHTTPHeaderField: "User-Agent")
        // Historical compatibility marker: CorgiLusi-iOS-User/2.9.0
        request.setValue("ios-user", forHTTPHeaderField: "X-Shop-Client")


        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let idempotency { request.setValue(idempotency, forHTTPHeaderField: "Idempotency-Key") }
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
        if !(200...299).contains(status) { throw NSError(domain: "shop", code: status, userInfo: [NSLocalizedDescriptionKey: detailOf(payload, status)]) }
        if payload.isEmpty { return [String: Any]() }
        let decoded = try JSONSerialization.jsonObject(with: payload)
        if let verifier, var result = decoded as? [String: Any], let code = result["authorization_code"] as? String {
            let exchanged = try call("POST", "/api/auth/mobile/token", body: ["code": code, "code_verifier": verifier]) as? [String: Any]
            result.removeValue(forKey: "authorization_code")
            result["access_token"] = exchanged?["access_token"]
            result["token_type"] = "bearer"
            return result
        }
        return decoded
    }

    func bytes(_ path: String) throws -> Data {
        guard let safe = safeMediaPath(path), let url = URL(string: base + safe) else { throw URLError(.badURL) }
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
        DispatchQueue.main.async { PushCenter.shared.openNotifications = true }
        completionHandler()
    }
}
