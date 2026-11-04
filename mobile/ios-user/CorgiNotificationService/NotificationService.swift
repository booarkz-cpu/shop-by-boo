import UserNotifications

/// Rich pushes of the shop (push style from «Стиль push-уведомлений»): APNs sends
/// `mutable-content: 1` and the picture URL in `image`; this extension downloads it (https only,
/// up to 10 MB, within the ~30 s iOS gives) and attaches it. The buttons come from the category the
/// app registered from GET /api/mobile/push-style. If anything fails the push is shown as it came.
///
/// The download callback and the time-out run on different threads, so `lock` guards the state.
final class NotificationService: UNNotificationServiceExtension, @unchecked Sendable {
    private let lock = NSLock()
    private var handler: ((UNNotificationContent) -> Void)?
    private var content: UNMutableNotificationContent?
    private var task: URLSessionDownloadTask?
    static let maxBytes: Int64 = 10 * 1024 * 1024

    override func didReceive(_ request: UNNotificationRequest, withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void) {
        let content = (request.content.mutableCopy() as? UNMutableNotificationContent) ?? UNMutableNotificationContent()
        lock.lock()
        handler = contentHandler
        self.content = content
        lock.unlock()
        guard let raw = request.content.userInfo["image"] as? String, let url = URL(string: raw), url.scheme == "https" else {
            return contentHandler(content)
        }
        let download = URLSession.shared.downloadTask(with: url) { [weak self] location, response, _ in
            guard let self else { return }
            defer { self.finish() }
            guard let location, let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
                  http.expectedContentLength <= Self.maxBytes,
                  let type = (http.mimeType ?? "").split(separator: "/").last.map(String.init), ["jpeg", "jpg", "png", "gif", "webp"].contains(type)
            else { return }
            let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + "." + (type == "jpeg" ? "jpg" : type))
            do {
                try FileManager.default.moveItem(at: location, to: file)
                let size = (try? FileManager.default.attributesOfItem(atPath: file.path)[.size] as? Int64) ?? 0
                guard size > 0, size <= Self.maxBytes else { return }
                let attachment = try UNNotificationAttachment(identifier: "image", url: file)
                self.lock.lock()
                self.content?.attachments = [attachment]
                self.lock.unlock()
            } catch {
                return
            }
        }
        lock.lock()
        task = download
        lock.unlock()
        download.resume()
    }

    override func serviceExtensionTimeWillExpire() {
        lock.lock()
        let running = task
        lock.unlock()
        running?.cancel()
        finish()
    }

    /// Hands the content over once: whichever of the download and the time-out comes first.
    private func finish() {
        lock.lock()
        let pending = handler, ready = content
        handler = nil
        lock.unlock()
        guard let pending, let ready else { return }
        pending(ready)
    }
}
