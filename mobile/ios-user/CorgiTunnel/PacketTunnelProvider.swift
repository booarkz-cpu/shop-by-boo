import Foundation
import NetworkExtension
import os.log

#if canImport(LibXray)
import LibXray
#endif
#if canImport(HevSocks5Tunnel)
import HevSocks5Tunnel
#endif

/// The embedded VPN of the iOS app: Xray-core (LibXray.xcframework, XTLS/libXray, MPL-2.0) with a
/// SOCKS inbound, fed from the packet flow by hev-socks5-tunnel (HevSocks5Tunnel.xcframework, MIT).
///
/// Both frameworks are built by scripts/ios/build-tunnel-frameworks.sh. Without them this target
/// still compiles and refuses to start with a clear message, so the app keeps handing the
/// subscription to an installed client. The extension is embedded only by
/// scripts/ios/enable-extensions.py, when the owner's Apple account has the Network Extension
/// entitlement: the default build and its signing stay exactly as before.
final class PacketTunnelProvider: NEPacketTunnelProvider {
    private let log = OSLog(subsystem: "shop.remnawave.user.tunnel", category: "tunnel")
    private var tunnelThread: Thread?

    private var shared: UserDefaults? { UserDefaults(suiteName: CorgiXray.appGroup) }

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        #if canImport(LibXray) && canImport(HevSocks5Tunnel)
        let configuration = (protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration ?? [:]
        guard let subscription = configuration["subscription"] as? String, subscription.hasPrefix("https://"),
              let url = URL(string: subscription) else {
            return fail("Нет ссылки подписки", completionHandler)
        }
        var request = URLRequest(url: url, timeoutInterval: 20)
        request.setValue("v2rayNG/1.10.0 CorgiLusi", forHTTPHeaderField: "User-Agent")  // Remnawave answers v2ray clients with share links
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self else { return }
            guard error == nil, let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
                  let body = data.flatMap({ String(data: $0, encoding: .utf8) }) else {
                return self.fail("Подписка недоступна", completionHandler)
            }
            let servers = CorgiXray.parseAll(body)
            guard !servers.isEmpty else { return self.fail("В подписке нет серверов", completionHandler) }
            self.shared?.set(servers.map(\.name), forKey: CorgiXray.keyServers)
            let xray = CorgiXray.config(servers, selected: self.shared?.string(forKey: CorgiXray.keyServer) ?? "",
                                         bypassRussian: self.shared?.bool(forKey: CorgiXray.keyBypassRu) ?? false)
            self.setTunnelNetworkSettings(Self.networkSettings()) { error in
                if let error { return self.fail(error.localizedDescription, completionHandler) }
                if let problem = Self.runXray(xray) { return self.fail(problem, completionHandler) }
                guard let fd = self.tunnelDescriptor() else {
                    Self.stopXray()
                    return self.fail("Не найден дескриптор туннеля", completionHandler)
                }
                let yaml = CorgiXray.tunnelConfig()
                let thread = Thread {
                    let bytes = Array(yaml.utf8)
                    _ = hev_socks5_tunnel_main_from_str(bytes, UInt32(bytes.count), fd)
                }
                thread.name = "hev-socks5-tunnel"
                thread.start()
                self.tunnelThread = thread
                self.shared?.removeObject(forKey: CorgiXray.keyError)
                os_log("tunnel up with %d servers", log: self.log, type: .info, servers.count)
                completionHandler(nil)
            }
        }.resume()
        #else
        fail("Встроенный VPN не собран в этой версии: подключитесь через Happ или v2RayTun", completionHandler)
        #endif
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        #if canImport(LibXray) && canImport(HevSocks5Tunnel)
        hev_socks5_tunnel_quit()
        Self.stopXray()
        #endif
        tunnelThread = nil
        completionHandler()
    }

    /// The app asks to reconnect after «Сервер VPN» or «Что работает без VPN» changed.
    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
        if String(data: messageData, encoding: .utf8) == "reload" {
            reasserting = true
            stopTunnel(with: .configurationFailed) { [weak self] in
                self?.startTunnel(options: nil) { error in
                    self?.reasserting = false
                    completionHandler?(error.map { Data($0.localizedDescription.utf8) })
                }
            }
        } else {
            completionHandler?(nil)
        }
    }

    private func fail(_ message: String, _ completion: @escaping (Error?) -> Void) {
        shared?.set(message, forKey: CorgiXray.keyError)
        os_log("tunnel failed: %{public}@", log: log, type: .error, message)
        completion(NSError(domain: "CorgiTunnel", code: 1, userInfo: [NSLocalizedDescriptionKey: message]))
    }

    static func networkSettings() -> NEPacketTunnelNetworkSettings {
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: "127.0.0.1")
        settings.mtu = 1500
        let ipv4 = NEIPv4Settings(addresses: ["198.18.0.1"], subnetMasks: ["255.255.255.0"])
        ipv4.includedRoutes = [NEIPv4Route.default()]
        settings.ipv4Settings = ipv4
        let ipv6 = NEIPv6Settings(addresses: ["fd6e:a81b:704f:1735::1"], networkPrefixLengths: [64])
        ipv6.includedRoutes = [NEIPv6Route.default()]
        settings.ipv6Settings = ipv6
        let dns = NEDNSSettings(servers: ["1.1.1.1", "8.8.8.8"])
        dns.matchDomains = [""]
        settings.dnsSettings = dns
        return settings
    }

    #if canImport(LibXray)
    /// LibXray's single entry point: Invoke(requestJSON) → {"success": bool, "error": "..."}.
    static func runXray(_ config: String) -> String? {
        let request: [String: Any] = ["apiVersion": 2, "method": "runXray", "payload": ["xrayJson": config]]
        guard let data = try? JSONSerialization.data(withJSONObject: request), let json = String(data: data, encoding: .utf8) else {
            return "Не удалось подготовить конфигурацию"
        }
        let answer = LibXrayInvoke(json)
        guard let body = answer.data(using: .utf8), let parsed = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else {
            return "Xray не ответил"
        }
        return (parsed["success"] as? Bool) == true ? nil : (parsed["error"] as? String ?? "Xray не запустился")
    }

    static func stopXray() {
        _ = LibXrayInvoke(#"{"apiVersion":2,"method":"stopXray","payload":{}}"#)
    }
    #else
    static func runXray(_ config: String) -> String? { "Xray не собран" }
    static func stopXray() {}
    #endif

    /// File descriptor of the utun interface: the packet flow's socket (older iOS) or the utun
    /// control socket found by its kernel control id.
    private func tunnelDescriptor() -> Int32? {
        if let fd = packetFlow.value(forKeyPath: "socket.fileDescriptor") as? Int32 { return fd }
        var info = CtlInfo()
        let name = Array("com.apple.net.utun_control".utf8CString)
        withUnsafeMutableBytes(of: &info.name) { raw in
            raw.copyBytes(from: name.map { UInt8(bitPattern: $0) }.prefix(raw.count))
        }
        for fd: Int32 in 0...1024 {
            var address = SockaddrCtl()
            var length = socklen_t(MemoryLayout<SockaddrCtl>.size)
            let peer = withUnsafeMutablePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getpeername(fd, $0, &length) }
            }
            guard peer == 0, address.family == 32 else { continue }  // AF_SYSTEM
            if info.id == 0, ioctl(fd, CtlInfo.ctliocginfo, &info) != 0 { continue }
            if address.id == info.id { return fd }
        }
        return nil
    }
}

/// struct ctl_info and struct sockaddr_ctl of <sys/kern_control.h>, which the iOS SDK does not import.
private struct CtlInfo {
    static let ctliocginfo: UInt = 0xC064_4E03  // _IOWR('N', 3, struct ctl_info)
    var id: UInt32 = 0
    var name: (UInt64, UInt64, UInt64, UInt64, UInt64, UInt64, UInt64, UInt64, UInt64, UInt64, UInt64, UInt64) =
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)  // char ctl_name[96]
}

private struct SockaddrCtl {
    var length: UInt8 = 0
    var family: UInt8 = 0
    var sysaddr: UInt16 = 0
    var id: UInt32 = 0
    var unit: UInt32 = 0
    var reserved: (UInt32, UInt32, UInt32, UInt32, UInt32) = (0, 0, 0, 0, 0)
}
