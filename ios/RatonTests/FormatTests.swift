import XCTest
@testable import Raton

/// The short writings of the YouTube search rows and the links the search field recognises.
final class FormatTests: XCTestCase {
    func testViews() {
        XCTAssertEqual(Format.views(1), "1 vue")
        XCTAssertEqual(Format.views(950), "950 vues")
        XCTAssertEqual(Format.views(1_200), "1,2 k vues")
        XCTAssertEqual(Format.views(3_400_000), "3,4 M vues")
        XCTAssertNil(Format.views(nil))
    }

    func testAge() {
        let now = ISO8601DateFormatter().date(from: "2026-11-17T12:00:00Z")!
        XCTAssertEqual(Format.age("2023-11-10T00:00:00", now: now), "il y a 3 ans")
        XCTAssertNil(Format.age("2030-01-01T00:00:00", now: now))
        XCTAssertNil(Format.age(nil, now: now))
    }

    func testYoutubeVideoLink() {
        XCTAssertNotNil(Format.youtubeVideoLink("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        XCTAssertNotNil(Format.youtubeVideoLink("youtu.be/dQw4w9WgXcQ"))
        XCTAssertNotNil(Format.youtubeVideoLink("https://m.youtube.com/shorts/abc123"))
        XCTAssertNil(Format.youtubeVideoLink("https://www.youtube.com/@channel"))
        XCTAssertNil(Format.youtubeVideoLink("rick astley"))
        XCTAssertNil(Format.youtubeVideoLink("https://example.com/watch?v=abc"))
    }
}
