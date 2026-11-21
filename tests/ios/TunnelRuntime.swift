import Darwin
import Foundation
import HevSocks5Tunnel
import LibXray

private struct Failure: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { description = message }
}

private func loopback(_ type: Int32, _ port: UInt16) throws -> Int32 {
    let fd = socket(AF_INET, type, 0)
    guard fd >= 0 else { throw Failure("socket: \(errno)") }
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_port = port.bigEndian
    address.sin_addr.s_addr = inet_addr("127.0.0.1")
    let result = withUnsafePointer(to: &address) { p in
        p.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    guard result == 0 else { close(fd); throw Failure("connect: \(errno)") }
    return fd
}

private func sendMarker(_ fd: Int32, _ text: String) throws {
    let data = Array(text.utf8)
    guard data.withUnsafeBytes({ write(fd, $0.baseAddress, $0.count) }) == data.count else {
        throw Failure("writing on caller-owned fd: \(errno)")
    }
}

private func expect(_ fd: Int32, _ command: UInt8) throws {
    var byte: UInt8 = 0
    guard read(fd, &byte, 1) == 1, byte == command else { throw Failure("lost control connection") }
}

@main
private enum TunnelRuntime {
    static func main() throws {
        let ports = CommandLine.arguments.dropFirst().compactMap(UInt16.init)
        guard ports.count == 3 else { throw Failure("expected control, tunnel and endpoint ports") }
        let control = try loopback(SOCK_STREAM, ports[0])
        defer { close(control) }
        let fd = try loopback(SOCK_DGRAM, ports[1])
        defer { close(fd) }
        let endpoint = CorgiServer(name: "test", outbound: [
            "tag": "proxy-0", "protocol": "freedom", "settings": ["redirect": "127.0.0.1:\(ports[2])"],
        ])
        let config = CorgiXray.config([endpoint], selected: endpoint.name, bypassRussian: false)
        let yaml = CorgiXray.tunnelConfig()
        let engine = CorgiPacketEngine()

        let cancelled = engine.begin()
        _ = engine.stop()
        guard engine.start(cancelled, config: config, yaml: yaml, fd: fd) != nil else {
            throw Failure("a cancelled subscription callback started the engine")
        }
        for cycle in 1...2 {
            if let error = engine.start(engine.begin(), config: config, yaml: yaml, fd: fd) {
                throw Failure("native start \(cycle): \(error)")
            }
            try sendMarker(fd, "ready-\(cycle)")
            try expect(control, 83) // S: traffic assertions completed
            if let error = engine.stop() { throw Failure("native stop \(cycle): \(error)") }
            guard fcntl(fd, F_GETFD) >= 0 else { throw Failure("hev closed its caller's fd") }
            try sendMarker(fd, "stopped-\(cycle)")
            try expect(control, 78) // N: the host observed shutdown
        }
    }
}
