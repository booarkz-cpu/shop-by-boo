import Foundation

/// One server of the subscription: its name and the Xray outbound built from its share link.
struct CorgiServer {
    let name: String
    let outbound: [String: Any]
}

/// Share links of a Remnawave subscription (vless://, vmess://, trojan://, ss://) → Xray config.
/// The same rules as the Android engine (ShareLinks.kt, XrayEngine.kt); on iOS the tunnel side is
/// a SOCKS inbound that hev-socks5-tunnel feeds from the packet flow.
enum CorgiXray {
    static let socksPort = 10808
    static let appGroup = "group.shop.remnawave.user"
    static let keyServer = "vpn_server"
    static let keyBypassRu = "vpn_bypass_ru"
    /// Extra sites around the VPN from the shop's signed list (CorgiMirrors).
    static let keyDirectExtra = "vpn_direct_extra"
    static let keyServers = "vpn_servers"
    static let keyError = "vpn_error"

    static func decodeSubscription(_ body: String) -> [String] {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        var plain = text
        if !text.contains("://") {
            plain = base64Text(text.replacingOccurrences(of: "\n", with: "").replacingOccurrences(of: "\r", with: "")) ?? ""
        }
        return plain.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }.filter { $0.contains("://") }
    }

    static func parseAll(_ body: String) -> [CorgiServer] {
        decodeSubscription(body).enumerated().compactMap { index, link in parse(link, tag: "proxy-\(index)") }
    }

    static func parse(_ link: String, tag: String) -> CorgiServer? {
        if link.hasPrefix("vless://") { return vless(link, tag) }
        if link.hasPrefix("vmess://") { return vmess(link, tag) }
        if link.hasPrefix("trojan://") { return trojan(link, tag) }
        if link.hasPrefix("ss://") { return shadowsocks(link, tag) }
        return nil
    }

    // MARK: - links

    static func base64Text(_ value: String) -> String? {
        var s = value.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while s.count % 4 != 0 { s += "=" }
        guard let data = Data(base64Encoded: s) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func query(_ components: URLComponents) -> [String: String] {
        var out: [String: String] = [:]
        for item in components.queryItems ?? [] { out[item.name] = item.value ?? "" }
        return out
    }

    private static func name(_ components: URLComponents, _ fallback: String) -> String {
        let fragment = components.fragment ?? ""
        return fragment.isEmpty ? fallback : fragment
    }

    private static func vless(_ link: String, _ tag: String) -> CorgiServer? {
        guard let c = URLComponents(string: link), let host = c.host, let port = c.port else { return nil }
        let p = query(c)
        var user: [String: Any] = ["id": c.user ?? "", "encryption": (p["encryption"] ?? "").isEmpty ? "none" : p["encryption"]!]
        if let flow = p["flow"], !flow.isEmpty { user["flow"] = flow }
        let settings: [String: Any] = ["vnext": [["address": host, "port": port, "users": [user]]]]
        return CorgiServer(name: name(c, host), outbound: outbound(tag, "vless", settings, stream(p, p["type"] ?? "", p["security"] ?? "", host)))
    }

    private static func trojan(_ link: String, _ tag: String) -> CorgiServer? {
        guard let c = URLComponents(string: link), let host = c.host, let port = c.port else { return nil }
        let p = query(c)
        let password = (c.user ?? "").removingPercentEncoding ?? c.user ?? ""
        let settings: [String: Any] = ["servers": [["address": host, "port": port, "password": password]]]
        let security = (p["security"] ?? "").isEmpty ? "tls" : p["security"]!
        return CorgiServer(name: name(c, host), outbound: outbound(tag, "trojan", settings, stream(p, p["type"] ?? "", security, host)))
    }

    private static func vmess(_ link: String, _ tag: String) -> CorgiServer? {
        guard let text = base64Text(String(link.dropFirst("vmess://".count))), let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        func s(_ key: String) -> String { if let v = json[key] as? String { return v }; if let v = json[key] { return "\(v)" }; return "" }
        let host = s("add")
        guard let port = Int(s("port")) else { return nil }
        let user: [String: Any] = ["id": s("id"), "alterId": Int(s("aid")) ?? 0, "security": s("scy").isEmpty ? "auto" : s("scy")]
        let settings: [String: Any] = ["vnext": [["address": host, "port": port, "users": [user]]]]
        let params = ["type": s("net"), "host": s("host"), "path": s("path"), "sni": s("sni"), "alpn": s("alpn"), "fp": s("fp"),
                      "headerType": s("type"), "serviceName": s("path")]
        let stream = stream(params, s("net"), s("tls") == "tls" ? "tls" : "none", host)
        return CorgiServer(name: s("ps").isEmpty ? host : s("ps"), outbound: outbound(tag, "vmess", settings, stream))
    }

    private static func shadowsocks(_ link: String, _ tag: String) -> CorgiServer? {
        var method = "", password = "", host = "", port = 0
        let c = URLComponents(string: link)
        if let c, let h = c.host, let p = c.port {
            let info = (c.percentEncodedUser ?? "").removingPercentEncoding ?? ""
            let decoded = info.contains(":") ? info : (base64Text(info) ?? "")
            guard let colon = decoded.firstIndex(of: ":") else { return nil }
            method = String(decoded[..<colon]); password = String(decoded[decoded.index(after: colon)...]); host = h; port = p
        } else {
            let body = String(link.dropFirst("ss://".count).split(separator: "#", maxSplits: 1).first ?? "")
            guard let raw = base64Text(body), let at = raw.lastIndex(of: "@"), let colon = raw.firstIndex(of: ":") else { return nil }
            method = String(raw[..<colon]); password = String(raw[raw.index(after: colon)..<at])
            let address = raw[raw.index(after: at)...]
            guard let last = address.lastIndex(of: ":"), let p = Int(address[address.index(after: last)...]) else { return nil }
            host = String(address[..<last]); port = p
        }
        let settings: [String: Any] = ["servers": [["address": host, "port": port, "method": method, "password": password]]]
        return CorgiServer(name: c.map { name($0, host) } ?? host, outbound: outbound(tag, "shadowsocks", settings, nil))
    }

    private static func outbound(_ tag: String, _ proto: String, _ settings: [String: Any], _ stream: [String: Any]?) -> [String: Any] {
        var row: [String: Any] = ["tag": tag, "protocol": proto, "settings": settings]
        if let stream { row["streamSettings"] = stream }
        return row
    }

    /// streamSettings: transport (tcp, ws, grpc, xhttp, httpupgrade) and security (tls, reality).
    static func stream(_ p: [String: String], _ rawNetwork: String, _ rawSecurity: String, _ host: String) -> [String: Any] {
        var network = rawNetwork.isEmpty ? "tcp" : rawNetwork
        if ["h2", "http", "splithttp"].contains(network) { network = "xhttp" }
        var stream: [String: Any] = ["network": network]
        let path = (p["path"] ?? "").removingPercentEncoding ?? ""
        let hostHeader = p["host"] ?? ""
        func withHost(_ value: [String: Any]) -> [String: Any] { var v = value; if !hostHeader.isEmpty { v["host"] = hostHeader }; return v }
        switch network {
        case "ws": stream["wsSettings"] = withHost(["path": path.isEmpty ? "/" : path])
        case "grpc": stream["grpcSettings"] = ["serviceName": (p["serviceName"] ?? "").isEmpty ? path : p["serviceName"]!, "multiMode": p["mode"] == "multi"]
        case "xhttp": stream["xhttpSettings"] = withHost(["path": path.isEmpty ? "/" : path, "mode": (p["mode"] ?? "").isEmpty ? "auto" : p["mode"]!])
        case "httpupgrade": stream["httpupgradeSettings"] = withHost(["path": path.isEmpty ? "/" : path])
        case "tcp":
            if p["headerType"] == "http" {
                stream["tcpSettings"] = ["header": ["type": "http", "request": ["path": [path.isEmpty ? "/" : path], "headers": ["Host": [hostHeader.isEmpty ? host : hostHeader]]]]]
            }
        default: break
        }
        let sni = [p["sni"] ?? "", p["peer"] ?? "", hostHeader, host].first { !$0.isEmpty } ?? host
        let fingerprint = (p["fp"] ?? "").isEmpty ? "chrome" : p["fp"]!
        switch rawSecurity {
        case "tls":
            var tls: [String: Any] = ["serverName": sni, "fingerprint": fingerprint]
            if let alpn = p["alpn"], !alpn.isEmpty { tls["alpn"] = (alpn.removingPercentEncoding ?? alpn).split(separator: ",").map(String.init) }
            stream["security"] = "tls"; stream["tlsSettings"] = tls
        case "reality":
            stream["security"] = "reality"
            stream["realitySettings"] = ["serverName": sni, "fingerprint": fingerprint, "publicKey": p["pbk"] ?? "", "shortId": p["sid"] ?? "",
                                         "spiderX": (p["spx"] ?? "").removingPercentEncoding ?? ""]
        default: stream["security"] = "none"
        }
        return stream
    }

    // MARK: - config

    /// Xray config: SOCKS inbound for the packet tunnel, the servers, «Авто» (fastest answer) or one
    /// chosen server, and what goes around the VPN (local networks; Russian sites when asked).
    static func config(_ servers: [CorgiServer], selected: String, bypassRussian: Bool, extraDirect: [String] = []) -> String {
        var outbounds: [[String: Any]] = servers.map { $0.outbound }
        outbounds.append(["tag": "direct", "protocol": "freedom"])
        outbounds.append(["tag": "block", "protocol": "blackhole"])
        var rules: [[String: Any]] = [["type": "field", "outboundTag": "direct",
                                       "ip": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10"]]]
        if bypassRussian {
            rules.append(["type": "field", "outboundTag": "direct",
                          "domain": ["regexp:\\.ru$", "regexp:\\.su$", "regexp:\\.xn--p1ai$", "domain:gosuslugi.ru", "domain:nalog.gov.ru",
                                     "domain:sberbank.com", "domain:vk.com", "domain:vk.me", "domain:userapi.com", "domain:yandex.net", "domain:yandex.com", "domain:yastatic.net"] + extraDirect.map { "domain:\($0)" }])
        }
        var routing: [String: Any] = ["domainStrategy": "AsIs"]
        var config: [String: Any] = [
            "log": ["loglevel": "warning"],
            "dns": ["servers": ["1.1.1.1", "8.8.8.8"]],
            "inbounds": [["tag": "socks-in", "protocol": "socks", "listen": "127.0.0.1", "port": socksPort,
                          "settings": ["udp": true, "auth": "noauth"],
                          "sniffing": ["enabled": true, "destOverride": ["http", "tls", "quic"]]]],
            "outbounds": outbounds,
        ]
        let chosen = servers.first { $0.name == selected }
        if let only = chosen ?? (servers.count == 1 ? servers.first : nil) {
            rules.append(["type": "field", "network": "tcp,udp", "outboundTag": only.outbound["tag"] as? String ?? "proxy-0"])
        } else if let first = servers.first {
            config["observatory"] = ["subjectSelector": ["proxy-"], "probeURL": "https://www.gstatic.com/generate_204",
                                     "probeInterval": "1m", "enableConcurrency": true]
            routing["balancers"] = [["tag": "auto", "selector": ["proxy-"], "strategy": ["type": "leastPing"],
                                     "fallbackTag": first.outbound["tag"] as? String ?? "proxy-0"]]
            rules.append(["type": "field", "network": "tcp,udp", "balancerTag": "auto"])
        }
        routing["rules"] = rules
        config["routing"] = routing
        let data = (try? JSONSerialization.data(withJSONObject: config, options: [.sortedKeys])) ?? Data("{}".utf8)
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    /// hev-socks5-tunnel: the packet flow of the tunnel → the SOCKS inbound of Xray.
    static func tunnelConfig(mtu: Int = 1500) -> String {
        """
        tunnel:
          mtu: \(mtu)
        socks5:
          port: \(socksPort)
          address: 127.0.0.1
          udp: 'udp'
        misc:
          task-stack-size: 24576
          log-level: warn
        """
    }
}
