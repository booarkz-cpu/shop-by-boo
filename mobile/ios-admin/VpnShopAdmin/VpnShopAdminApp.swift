import CryptoKit
import Security
import SwiftUI

@main
struct VpnShopAdminApp: App {
    var body: some Scene {
        WindowGroup { AdminRootView() }
    }
}

private let localHttpHosts: Set<String> = ["localhost", "127.0.0.1", "10.0.2.2"]

func pkceVerifier() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw URLError(.unknown) }
    return Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
}
func pkceChallenge(_ verifier: String) -> String {
    Data(SHA256.hash(data: Data(verifier.utf8))).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
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

    func call(_ method: String, _ path: String, body: [String: Any]? = nil) throws -> Any {
        let verifier: String? = try (["/api/auth/login", "/api/auth/register", "/api/admin/auth/login"].contains(path) ? pkceVerifier() : nil)
        var request = URLRequest(url: URL(string: base + path)!)
        if let verifier { request.setValue(pkceChallenge(verifier), forHTTPHeaderField: "X-Shop-Code-Challenge") }
        request.httpMethod = method
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(lang, forHTTPHeaderField: "Accept-Language")
        request.setValue("CorgiLusi-iOS-Admin/2.16.0", forHTTPHeaderField: "User-Agent")
        // Historical compatibility marker: CorgiLusi-iOS-Admin/2.10.0
        // Historical compatibility marker: CorgiLusi-iOS-Admin/2.9.0
        request.setValue("ios-admin", forHTTPHeaderField: "X-Shop-Client")


        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
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
    /// Each admin profile has its own Keychain item; "session" is the original single session.
    private static func query(_ account: String = "session") -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: (Bundle.main.bundleIdentifier ?? "shop.session") + ".session.v2",
         kSecAttrAccount as String: account]
    }
    static func clear(account: String = "session") { SecItemDelete(query(account) as CFDictionary) }
    static func load(baseKey: String, legacyKey: String) -> String {
        UserDefaults.standard.removeObject(forKey: legacyKey)
        return load(account: "session", base: UserDefaults.standard.string(forKey: baseKey) ?? "")
    }
    static func load(account: String, base: String) -> String {
        var lookup = query(account)
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(lookup as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let stored = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              !base.isEmpty, stored["base"] == base else { return "" }
        return stored["token"] ?? ""
    }
    static func save(_ token: String, base: String, account: String = "session") throws {
        let item = query(account)
        let data = try JSONSerialization.data(withJSONObject: ["token": token, "base": base])
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var status = SecItemUpdate(item as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(item.merging(attributes) { _, new in new } as CFDictionary, nil)
        }
        guard status == errSecSuccess else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
    }
}


// MARK: - Admin profiles

/// One saved shop/admin connection; its session lives in a separate Keychain item.
struct AdminProfile: Codable, Identifiable, Equatable {
    let id: String
    var label: String
    var base: String
    var email: String
    var host: String { URL(string: base)?.host ?? base }
    var title: String { label.isEmpty ? host : label }
}

/// Several admin profiles on one device. The pre-multiprofile session becomes "default".
enum ProfileVault {
    static let maxProfiles = 8
    static let defaultId = "default"
    private static let listKey = "shop_admin_profiles"
    private static let activeKey = "shop_admin_active_profile"

    static func account(_ id: String) -> String { id == defaultId ? "session" : "session.\(id)" }

    static func all() -> [AdminProfile] {
        if let data = UserDefaults.standard.data(forKey: listKey) {
            return (try? JSONDecoder().decode([AdminProfile].self, from: data)) ?? []
        }
        let legacy = UserDefaults.standard.string(forKey: "shop_admin_base") ?? ""
        guard !legacy.isEmpty else { return [] }
        let list = [AdminProfile(id: defaultId, label: "", base: legacy, email: "")]
        save(list)
        return list
    }

    private static func save(_ list: [AdminProfile]) {
        if let data = try? JSONEncoder().encode(list) { UserDefaults.standard.set(data, forKey: listKey) }
    }

    static func find(_ id: String) -> AdminProfile? { all().first { $0.id == id } }

    static func activeId() -> String {
        let list = all()
        if let saved = UserDefaults.standard.string(forKey: activeKey), list.contains(where: { $0.id == saved }) { return saved }
        return list.first?.id ?? defaultId
    }

    static func setActive(_ id: String) { UserDefaults.standard.set(id, forKey: activeKey) }

    static func newId() -> String { String(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12)).lowercased() }

    static func token(_ id: String) -> String {
        guard let profile = find(id) else { return "" }
        return SessionKeychain.load(account: account(id), base: profile.base)
    }

    static func duplicate(of id: String, base: String, email: String) -> AdminProfile? {
        all().first { $0.id != id && $0.base == base && $0.email.caseInsensitiveCompare(email) == .orderedSame }
    }

    static func upsert(_ profile: AdminProfile) {
        save(all().filter { $0.id != profile.id } + [profile])
    }

    static func remove(_ id: String) {
        SessionKeychain.clear(account: account(id))
        save(all().filter { $0.id != id })
        if UserDefaults.standard.string(forKey: activeKey) == id { UserDefaults.standard.removeObject(forKey: activeKey) }
    }
}
