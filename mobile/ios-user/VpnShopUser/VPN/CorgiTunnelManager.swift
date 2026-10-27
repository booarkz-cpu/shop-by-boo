import Foundation
import NetworkExtension

/// «Подключить» inside the app (iOS): starts the CorgiTunnel packet tunnel extension.
///
/// Used only when the build embeds the extension (CORGI_TUNNEL = YES, set by
/// scripts/ios/enable-extensions.py for a team with the Network Extension entitlement). Otherwise
/// `available` is false and the app keeps handing the subscription to Happ / v2RayTun.
final class CorgiTunnelManager {
    static let shared = CorgiTunnelManager()
    static var available: Bool { (Bundle.main.object(forInfoDictionaryKey: "CorgiTunnelEnabled") as? String) == "YES" }
    static var providerBundleId: String { (Bundle.main.bundleIdentifier ?? "shop.remnawave.user") + ".tunnel" }

    private var manager: NETunnelProviderManager?
    private var observer: NSObjectProtocol?
    var onStatus: ((NEVPNStatus) -> Void)?

    private var shared: UserDefaults? { UserDefaults(suiteName: CorgiXray.appGroup) }

    var status: NEVPNStatus { manager?.connection.status ?? .invalid }
    var lastError: String? { shared?.string(forKey: CorgiXray.keyError) }
    var servers: [String] { shared?.stringArray(forKey: CorgiXray.keyServers) ?? [] }
    var server: String {
        get { shared?.string(forKey: CorgiXray.keyServer) ?? "" }
        set { shared?.set(newValue, forKey: CorgiXray.keyServer); reload() }
    }
    var bypassRussian: Bool {
        get { shared?.bool(forKey: CorgiXray.keyBypassRu) ?? false }
        set { shared?.set(newValue, forKey: CorgiXray.keyBypassRu); reload() }
    }

    func load(_ done: @escaping () -> Void = {}) {
        guard Self.available else { return done() }
        NETunnelProviderManager.loadAllFromPreferences { [weak self] managers, _ in
            guard let self else { return }
            self.manager = managers?.first { ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == Self.providerBundleId }
            self.watch()
            DispatchQueue.main.async { self.onStatus?(self.status); done() }
        }
    }

    func connect(subscription: String, _ completion: @escaping (Error?) -> Void) {
        guard Self.available, subscription.hasPrefix("https://") else {
            return completion(NSError(domain: "CorgiTunnel", code: 2, userInfo: [NSLocalizedDescriptionKey: "Нет подписки"]))
        }
        load { [weak self] in
            guard let self else { return }
            let manager = self.manager ?? NETunnelProviderManager()
            let proto = (manager.protocolConfiguration as? NETunnelProviderProtocol) ?? NETunnelProviderProtocol()
            proto.providerBundleIdentifier = Self.providerBundleId
            proto.serverAddress = "Corgi Lusi"
            proto.providerConfiguration = ["subscription": subscription]
            proto.disconnectOnSleep = false
            manager.protocolConfiguration = proto
            manager.localizedDescription = "Corgi Lusi"
            manager.isEnabled = true
            manager.saveToPreferences { error in
                if let error { return DispatchQueue.main.async { completion(error) } }
                // A saved configuration must be loaded again before it can start.
                manager.loadFromPreferences { error in
                    if let error { return DispatchQueue.main.async { completion(error) } }
                    self.manager = manager
                    self.watch()
                    do {
                        try manager.connection.startVPNTunnel()
                        DispatchQueue.main.async { completion(nil) }
                    } catch {
                        DispatchQueue.main.async { completion(error) }
                    }
                }
            }
        }
    }

    func disconnect() { manager?.connection.stopVPNTunnel() }

    /// After «Сервер VPN» or «Что работает без VPN» changed: the running tunnel rebuilds its config.
    func reload() {
        guard let session = manager?.connection as? NETunnelProviderSession, session.status == .connected else { return }
        try? session.sendProviderMessage(Data("reload".utf8)) { _ in }
    }

    private func watch() {
        guard observer == nil, let connection = manager?.connection else { return }
        observer = NotificationCenter.default.addObserver(forName: .NEVPNStatusDidChange, object: connection, queue: .main) { [weak self] _ in
            guard let self else { return }
            self.onStatus?(self.status)
        }
    }
}
