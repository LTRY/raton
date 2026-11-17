import SwiftUI

/// Why the loaded file does not play, with a button that loads it again.
struct PlaybackErrorMessage: View {
    @EnvironmentObject private var player: PlayerController
    let retry: () -> Void

    var body: some View {
        ErrorMessage(text: player.playbackError, retry: retry)
    }
}
