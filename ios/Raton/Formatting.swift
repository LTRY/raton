import Foundation

/// French display of what the API gives raw (seconds, ...); the app only formats, the back decides.
enum Format {
    static func clock(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0 else { return "0:00" }
        let total = Int(seconds)
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let secs = total % 60
        return hours > 0
            ? String(format: "%d:%02d:%02d", hours, minutes, secs)
            : String(format: "%d:%02d", minutes, secs)
    }

    /// "2026-10-18T13:47:55.88" as "Dim. 18 oct. 2026"; the API gives the date, the app only writes it.
    static func frenchDate(_ iso: String?) -> String? {
        guard let iso, iso.count >= 10 else { return nil }
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: String(iso.prefix(10))) else { return nil }
        let writer = DateFormatter()
        writer.locale = Locale(identifier: "fr_FR")
        writer.dateFormat = "EEE dd MMM yyyy"
        let text = writer.string(from: date)
        return text.prefix(1).uppercased() + text.dropFirst()
    }
}
