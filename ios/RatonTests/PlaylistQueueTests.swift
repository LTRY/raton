import XCTest
@testable import Raton

/// The order a playlist plays in (`PlaylistQueue`), the rules of the web's playlist player.
final class PlaylistQueueTests: XCTestCase {
    private func track(_ id: Int, audio: Bool = true, video: Bool = false) -> QueueTrack {
        QueueTrack(videoID: id, title: "Piste \(id)", channelName: nil, durationSeconds: 60,
                   hasAudio: audio, hasVideo: video, hasThumbnail: false)
    }

    private func queue(_ tracks: [QueueTrack], mode: MediaKind = .audio, shuffle: Bool = false,
                       loop: Bool = false) -> PlaylistQueue {
        PlaylistQueue(playlistID: 1, title: "Test", free: false, tracks: tracks, mode: mode, shuffle: shuffle, loop: loop)
    }

    func testNextFollowsTheOrderAndStopsAtTheEnd() {
        var queue = queue([track(1), track(2), track(3)])
        queue.pick(1)

        XCTAssertEqual(queue.next()?.videoID, 2)
        XCTAssertEqual(queue.next()?.videoID, 3)
        XCTAssertNil(queue.next())
        XCTAssertEqual(queue.current, 3)
    }

    func testLoopGoesBackToTheFirstTrack() {
        var queue = queue([track(1), track(2)], loop: true)
        queue.pick(2)

        XCTAssertEqual(queue.next()?.videoID, 1)
    }

    func testATrackWithoutTheFileOfTheModeIsSkipped() {
        var queue = queue([track(1), track(2, audio: false, video: true), track(3)])
        queue.pick(1)

        XCTAssertEqual(queue.eligible.map(\.videoID), [1, 3])
        XCTAssertEqual(queue.next()?.videoID, 3)
    }

    func testNextFromATrackNotPlayableInThisModeTakesTheNextPlayableOne() {
        var queue = queue([track(1), track(2, audio: false, video: true), track(3)])
        queue.pick(2)

        XCTAssertEqual(queue.next()?.videoID, 3)
    }

    func testPreviousWalksBackAndStopsAtTheFirstTrack() {
        var queue = queue([track(1), track(2), track(3)])
        queue.pick(3)

        XCTAssertEqual(queue.previous()?.videoID, 2)
        XCTAssertEqual(queue.previous()?.videoID, 1)
        XCTAssertNil(queue.previous())
    }

    func testShufflePlaysEveryTrackOnceBeforeItStops() {
        var queue = queue((1...6).map { track($0) }, shuffle: true)
        queue.pick(1)
        var played = [1]

        while let following = queue.next() { played.append(following.videoID) }

        XCTAssertEqual(played.count, 6)
        XCTAssertEqual(Set(played), Set(1...6))
    }

    func testShufflePreviousGoesBackToWhatWasPlayed() {
        var queue = queue((1...6).map { track($0) }, shuffle: true)
        queue.pick(1)
        let second = queue.next()?.videoID
        _ = queue.next()

        XCTAssertEqual(queue.previous()?.videoID, second)
        XCTAssertEqual(queue.previous()?.videoID, 1)
    }

    func testUpdateKeepsTheCurrentTrackWhileItIsStillInTheRows() {
        var queue = queue([track(1), track(2), track(3)])
        queue.pick(2)

        queue.update(tracks: [track(3), track(2)])
        XCTAssertEqual(queue.current, 2)
        XCTAssertEqual(queue.currentNumber, 2)

        queue.update(tracks: [track(3)])
        XCTAssertNil(queue.current)
    }
}
