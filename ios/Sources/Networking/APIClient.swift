import Foundation

// MARK: - Server configuration

struct ServerConfig: Codable, Equatable {
    /// Production default: the Render free-tier web service for this project.
    /// Password is never shipped in source — set once in Settings.
    static let cloudDefaultURL = "https://sleep-tracker-n4cs.onrender.com"
    static let localDefaultURL = "http://127.0.0.1:8080"

    var baseURL: String = ServerConfig.cloudDefaultURL
    var username: String = "sleep"
    var password: String = ""

    var normalizedBase: String {
        var s = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        return s
    }

    var isConfigured: Bool {
        !normalizedBase.isEmpty && URL(string: normalizedBase) != nil
    }

    var hasCredentials: Bool {
        !username.isEmpty && !password.isEmpty
    }
}

enum APIError: LocalizedError {
    case badURL
    case server(status: Int, message: String)
    case decoding(String)
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "The server URL is not valid."
        case .server(let status, let message):
            return message.isEmpty ? "Server error (\(status))." : message
        case .decoding(let detail):
            return "Unexpected response from the server. \(detail)"
        case .transport(let detail):
            return detail
        }
    }
}

// MARK: - Client

struct APIClient {
    var config: ServerConfig

    private static let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        // Render free tier cold-starts can exceed 30s; keep client patient.
        cfg.timeoutIntervalForRequest = 90
        cfg.timeoutIntervalForResource = 120
        cfg.waitsForConnectivity = true
        return URLSession(configuration: cfg)
    }()

    static let decoder = JSONDecoder()

    // MARK: GET endpoints

    func stats() async throws -> Stats {
        try await get("/api/stats")
    }

    func records(limit: Int = 10_000) async throws -> [SleepRecord] {
        try await get("/api/records?limit=\(limit)")
    }

    func series(range: SeriesRange) async throws -> SeriesResponse {
        try await get("/api/series?range=\(range.rawValue)")
    }

    func insights() async throws -> InsightsResponse {
        try await get("/api/insights")
    }

    /// Lightweight connectivity probe; returns the stats it fetched.
    func testConnection() async throws -> Stats {
        try await stats()
    }

    // MARK: POST endpoints (form-encoded, AJAX header)

    struct NightFields {
        var date: String
        var bedtime: String
        var wake: String
        var quality: Int
        var notes: String

        var formItems: [(String, String)] {
            [
                ("date", date),
                ("bedtime", bedtime),
                ("wake", wake),
                ("quality", String(quality)),
                ("notes", notes),
            ]
        }
    }

    func add(_ fields: NightFields) async throws -> MutationResponse {
        try await post("/add", form: fields.formItems)
    }

    func edit(id: Int, fields: NightFields) async throws -> MutationResponse {
        try await post("/edit/\(id)", form: fields.formItems)
    }

    func delete(id: Int) async throws -> MutationResponse {
        try await post("/delete/\(id)", form: [])
    }

    // MARK: Wearable auto-sync (JSON ingest)

    /// One night for `POST /api/ingest` (Shortcuts / HealthKit push).
    struct IngestNight: Encodable {
        var date: String
        var bedtime: String
        var wake: String
        var quality: Int?
        var notes: String?
        var source: String
        var stages: SleepStages?
        var efficiency: Double?
    }

    struct IngestResponse: Decodable {
        let ok: Bool
        let imported: Int
        let replaced: Int
        let skipped: Int
        let stats: Stats?
        let errors: [IngestError]?
    }

    struct IngestError: Decodable {
        let index: Int?
        let error: String
    }

    /// Upsert nights as `apple_health` (or other source) via JSON ingest.
    func ingest(_ nights: [IngestNight]) async throws -> IngestResponse {
        try await postJSON("/api/ingest", body: nights)
    }

    // MARK: Internals

    private func url(_ path: String) throws -> URL {
        guard let url = URL(string: config.normalizedBase + path),
              let scheme = url.scheme, ["http", "https"].contains(scheme)
        else { throw APIError.badURL }
        return url
    }

    private func authorize(_ request: inout URLRequest) {
        guard !config.username.isEmpty || !config.password.isEmpty else { return }
        let raw = "\(config.username):\(config.password)"
        let token = Data(raw.utf8).base64EncodedString()
        request.setValue("Basic \(token)", forHTTPHeaderField: "Authorization")
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: try url(path))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        authorize(&request)
        let data = try await run(request)
        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }

    private func post(_ path: String, form: [(String, String)]) async throws -> MutationResponse {
        var request = URLRequest(url: try url(path))
        request.httpMethod = "POST"
        request.setValue("XMLHttpRequest", forHTTPHeaderField: "X-Requested-With")
        request.setValue("application/x-www-form-urlencoded; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        authorize(&request)
        request.httpBody = Self.encodeForm(form).data(using: .utf8)
        let data = try await run(request)
        do {
            return try Self.decoder.decode(MutationResponse.self, from: data)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }

    private func postJSON<Body: Encodable, T: Decodable>(_ path: String, body: Body) async throws -> T {
        var request = URLRequest(url: try url(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        authorize(&request)
        request.httpBody = try JSONEncoder().encode(body)
        let data = try await run(request)
        do {
            return try Self.decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }

    private func run(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await Self.session.data(for: request)
        } catch {
            throw APIError.transport((error as NSError).localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport("Not an HTTP response.")
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = (try? Self.decoder.decode(APIErrorBody.self, from: data))?.error ?? ""
            if http.statusCode == 401 {
                throw APIError.server(status: 401, message: "Authentication required — check your username and password in Settings.")
            }
            throw APIError.server(status: http.statusCode, message: message)
        }
        return data
    }

    static func encodeForm(_ items: [(String, String)]) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        return items.map { key, value in
            let k = key.addingPercentEncoding(withAllowedCharacters: allowed) ?? key
            let v = value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
            return "\(k)=\(v)"
        }.joined(separator: "&")
    }
}
