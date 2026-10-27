import UserNotifications

/// Rich pushes of the shop (push style from «Стиль push-уведомлений»): APNs sends
/// `mutable-content: 1` and the picture URL in `image`; this extension downloads it (https only,
/// up to 10 MB, within the ~30 s iOS gives) and attaches it. The buttons come from the category the
/// app registered from GET /api/mobile/push-style. If anything fails the push is shown as it came.
final class NotificationService: UNNotificationServiceExtension {
    private var handler: ((UNNotificationContent) -> Void)?
    private var content: UNMutableNotificationContent?
    private var task: URLSessionDownloadTask?
    static let maxBytes: Int64 = 10 * 1024 * 1024

    override func didReceive(_ request: UNNotificationRequest, withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void) {
        handler = contentHandler
        let content = (request.content.mutableCopy() as? UNMutableNotificationContent) ?? UNMutableNotificationContent()
        self.content = content
        guard let raw = request.content.userInfo["image"] as? String, let url = URL(string: raw), url.scheme == "https" else {
            return contentHandler(content)
        }
        task = URLSession.shared.downloadTask(with: url) { [weak self] location, response, _ in
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
                content.attachments = [try UNNotificationAttachment(identifier: "image", url: file)]
            } catch {
                return
            }
        }
        task?.resume()
    }

    override func serviceExtensionTimeWillExpire() {
        task?.cancel()
        finish()
    }

    private func finish() {
        guard let handler, let content else { return }
        self.handler = nil
        handler(content)
    }
}
