import Foundation

/// What the app remembers between launches: the server URL and the user, in UserDefaults.
final class AppState: ObservableObject {
    private static let serverKey = "serverURL"
    private static let userKey = "userID"

    @Published private(set) var serverURL: URL?
    @Published private(set) var userID: Int?

    init() {
        let defaults = UserDefaults.standard
        serverURL = defaults.string(forKey: Self.serverKey).flatMap { URL(string: $0) }
        // A launch argument (`-userID 1`, used by the UI tests) arrives as a string.
        userID = (defaults.object(forKey: Self.userKey) as? Int) ?? defaults.string(forKey: Self.userKey).flatMap(Int.init)
    }

    /// The client for the stored server and user; nil until a server is chosen.
    var api: RatonAPI? {
        serverURL.map { RatonAPI(baseURL: $0, userID: userID) }
    }

    func setServer(_ url: URL) {
        if url != serverURL {
            // Another server has other users.
            userID = nil
            UserDefaults.standard.removeObject(forKey: Self.userKey)
        }
        serverURL = url
        UserDefaults.standard.set(url.absoluteString, forKey: Self.serverKey)
    }

    func setUser(_ id: Int) {
        userID = id
        UserDefaults.standard.set(id, forKey: Self.userKey)
    }

    /// Back to the first-launch screen (a wrong server).
    func forgetServer() {
        serverURL = nil
        userID = nil
        UserDefaults.standard.removeObject(forKey: Self.serverKey)
        UserDefaults.standard.removeObject(forKey: Self.userKey)
    }
}
