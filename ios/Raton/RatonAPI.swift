import Foundation

/// A refused or failed call; `message` is in French and fit for the user (the back's own `detail`
/// when it sent one).
struct RatonError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// The app's only way to the data: HTTP calls to the front's URL, which relays `/api` to the back.
/// The Swift twin of `front/api.py`: every call carries the user in `X-Raton-User`.
final class RatonAPI {
    let baseURL: URL
    let userID: Int?
    private let session: URLSession
    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    init(baseURL: URL, userID: Int?) {
        self.baseURL = baseURL
        self.userID = userID
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 15
        configuration.waitsForConnectivity = false
        session = URLSession(configuration: configuration)
    }

    /// The URL of a path the API gave (`/api/videos/3/video`) or that the app builds.
    func url(_ path: String) -> URL {
        URL(string: baseURL.absoluteString + path) ?? baseURL
    }

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try decode(try await send("GET", path, query: query))
    }

    func post<T: Decodable>(_ path: String, body: [String: Any]? = nil) async throws -> T {
        try decode(try await send("POST", path, body: body))
    }

    func put<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        try decode(try await send("PUT", path, body: body))
    }

    func delete(_ path: String) async throws {
        _ = try await send("DELETE", path)
    }

    /// Polls `GET /api/llm-jobs/{id}` until the answer is written (the back applies a finished job on
    /// the poll that sees it), as the front's chat does.
    func waitForLLMJob(_ jobID: Int) async throws -> LLMJobStatus {
        while true {
            let job: LLMJobStatus = try await get("/api/llm-jobs/\(jobID)")
            if job.status == "failed" { throw RatonError(message: job.message ?? "Réponse impossible.") }
            if job.status == "done" || job.status == "applied" { return job }
            try await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw RatonError(message: "Réponse inattendue du serveur.")
        }
    }

    private func send(
        _ method: String, _ path: String, query: [String: String] = [:], body: [String: Any]? = nil
    ) async throws -> Data {
        var components = URLComponents(string: baseURL.absoluteString + path)
        if !query.isEmpty {
            components?.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        guard let url = components?.url else { throw RatonError(message: "Adresse invalide.") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let userID { request.setValue(String(userID), forHTTPHeaderField: "X-Raton-User") }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw RatonAPI.connectionError(error, host: baseURL.host)
        }
        guard let http = response as? HTTPURLResponse else {
            throw RatonError(message: "Réponse inattendue du serveur.")
        }
        guard http.statusCode < 400 else { throw RatonAPI.statusError(http.statusCode, data) }
        return data
    }

    private static func statusError(_ status: Int, _ data: Data) -> RatonError {
        // FastAPI answers `{"detail": "<French message>"}`; a validation error has a list instead.
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = json["detail"] as? String {
            return RatonError(message: detail)
        }
        return RatonError(message: "Le serveur a répondu une erreur (HTTP \(status)).")
    }

    /// Turns a network failure into a French message; the hint about the Local Network permission
    /// is given for hosts on the LAN, where iOS refusing access looks like an unreachable server.
    static func connectionError(_ error: Error, host: String?) -> RatonError {
        let nsError = error as NSError
        let underlying = nsError.userInfo[NSUnderlyingErrorKey] as? NSError
        let noRoute = underlying?.domain == NSPOSIXErrorDomain && underlying?.code == 65
        let hint =
            "Si le serveur tourne bien, vérifiez l'accès au réseau local : "
            + "Réglages → Raton → Réseau local."
        if noRoute {
            return RatonError(message: "Connexion au réseau local refusée. " + hint)
        }
        let onLAN = isLocalHost(host)
        switch (error as? URLError)?.code {
        case .cannotFindHost?:
            return RatonError(message: "Nom de serveur introuvable. Vérifiez l'adresse.")
        case .appTransportSecurityRequiresSecureConnection?:
            return RatonError(message: "Connexion non sécurisée refusée par iOS.")
        case .notConnectedToInternet?, .cannotConnectToHost?, .timedOut?, .networkConnectionLost?:
            let base = "Serveur injoignable."
            return RatonError(message: onLAN ? base + " " + hint : base + " Vérifiez l'adresse et le réseau.")
        default:
            return RatonError(message: "Serveur injoignable : \(error.localizedDescription)")
        }
    }

    private static func isLocalHost(_ host: String?) -> Bool {
        guard let host = host?.lowercased() else { return false }
        if host.hasSuffix(".local") || !host.contains(".") { return true }
        let parts = host.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4 else { return false }
        return parts[0] == 10 || parts[0] == 192 && parts[1] == 168
            || parts[0] == 172 && (16...31).contains(parts[1]) || parts[0] == 169 && parts[1] == 254
    }

    /// Reads what the user typed: adds `http://` when there is no scheme, drops a trailing slash.
    static func parseServerURL(_ text: String) -> URL? {
        var text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") { text = "http://" + text }
        while text.hasSuffix("/") { text.removeLast() }
        guard let url = URL(string: text), let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https", let host = url.host, !host.isEmpty
        else { return nil }
        return url
    }

    /// Validates a server URL: `GET {url}/api/users` must answer 200 with the users.
    static func checkServer(_ url: URL) async throws -> [RatonUser] {
        let reply: UsersReply = try await RatonAPI(baseURL: url, userID: nil).get("/api/users")
        return reply.users
    }

    func users() async throws -> UsersReply { try await get("/api/users") }
}
