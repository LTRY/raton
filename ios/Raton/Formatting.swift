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

    /// 1234 as "1,2 k vues", 3_400_000 as "3,4 M vues": the count the API gives, written short.
    static func views(_ count: Int?) -> String? {
        guard let count, count >= 0 else { return nil }
        let number = NumberFormatter()
        number.locale = Locale(identifier: "fr_FR")
        number.maximumFractionDigits = 1
        switch count {
        case 0..<1_000: return count == 1 ? "1 vue" : "\(count) vues"
        case 1_000..<1_000_000:
            return (number.string(from: NSNumber(value: Double(count) / 1_000)) ?? "\(count / 1_000)") + " k vues"
        default:
            return (number.string(from: NSNumber(value: Double(count) / 1_000_000)) ?? "\(count / 1_000_000)") + " M vues"
        }
    }

    /// "2023-05-01T..." as "il y a 3 ans", the way YouTube says it in its results.
    static func age(_ iso: String?, now: Date = Date()) -> String? {
        guard let iso, iso.count >= 10 else { return nil }
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: String(iso.prefix(10))), date <= now else { return nil }
        let writer = RelativeDateTimeFormatter()
        writer.locale = Locale(identifier: "fr_FR")
        writer.unitsStyle = .full
        return writer.localizedString(for: date, relativeTo: now)
    }
}
