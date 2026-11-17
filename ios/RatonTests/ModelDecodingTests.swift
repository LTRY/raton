import XCTest
@testable import Raton

/// Decodes real answers of the API (`Fixtures/*.json`, written by `scripts/ios_fixtures.py` from the
/// demo data) with the app's models, the way `RatonAPI` does. The back's own test
/// (`tests/test_ios_fixtures.py`) keeps those files true to what the API answers.
final class ModelDecodingTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, from name: String) throws -> T {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json"),
                                "Fixture \(name).json is not in the test bundle")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: Data(contentsOf: url))
    }

    func testUsers() throws {
        XCTAssertFalse(try decode(UsersReply.self, from: "users").users.isEmpty)
    }

    func testLibrary() throws {
        let reply = try decode(LibraryReply.self, from: "library")
        XCTAssertFalse(reply.items.isEmpty)
        XCTAssertEqual(reply.total, reply.items.count)
    }

    func testLibraryOfAChannelHasItsCounts() throws {
        let reply = try decode(LibraryReply.self, from: "library_channel")
        XCTAssertNotNil(reply.counts)
        XCTAssertNotNil(reply.exploreNextPage)
    }

    func testVideo() throws {
        let detail = try decode(VideoDetail.self, from: "video")
        XCTAssertEqual(detail.id, 1)
        XCTAssertNotNil(detail.channel)
    }

    func testChannels() throws {
        XCTAssertFalse(try decode(ChannelsReply.self, from: "channels").items.isEmpty)
    }

    func testChannel() throws {
        XCTAssertEqual(try decode(ChannelDetail.self, from: "channel").id, 1)
    }

    func testPlaylists() throws {
        XCTAssertEqual(try decode([PlaylistSummary].self, from: "playlists").first?.itemCount, 2)
    }

    func testPlaylist() throws {
        XCTAssertEqual(try decode(PlaylistDetail.self, from: "playlist").items.count, 2)
    }

    func testHistorique() throws {
        XCTAssertFalse(try decode(HistoriqueReply.self, from: "historique").rows.isEmpty)
    }

    func testSettings() throws {
        _ = try decode(UserSettings.self, from: "settings")
    }

    func testScreenTime() throws {
        _ = try decode(ScreenTimeReply.self, from: "screen_time")
    }

    func testCategories() throws {
        _ = try decode([CategoryStyle].self, from: "categories")
    }
}
