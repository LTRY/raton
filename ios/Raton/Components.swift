import AVKit
import SwiftUI

/// The rounded search field of the web's list pages.
struct SearchField: View {
    let placeholder: String
    @Binding var text: String
    let onSubmit: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass").foregroundStyle(Theme.textMuted)
            TextField(placeholder, text: $text)
                .font(.raton(16, .semibold))
                .submitLabel(.search)
                .autocorrectionDisabled()
                .onSubmit(onSubmit)
            if !text.isEmpty {
                Button {
                    text = ""
                    onSubmit()
                } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.textFaint)
                }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .surface(in: Capsule())
        .padding(.horizontal, 16).padding(.bottom, 12)
    }
}

struct EmptyMessage: View {
    let text: String
    var body: some View {
        Text(text).font(.raton(16)).foregroundStyle(Theme.textMuted)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity).padding(.top, 60).padding(.horizontal, 24)
    }
}

/// The error of a failed call; with `retry`, a button tries the call again.
struct ErrorMessage: View {
    let text: String?
    var retry: (() -> Void)? = nil

    var body: some View {
        if let text {
            VStack(alignment: .leading, spacing: 10) {
                Text(text).font(.raton(15, .medium)).foregroundStyle(Theme.danger)
                if let retry {
                    Button("Réessayer", action: retry).buttonStyle(SandButtonStyle(fill: false))
                }
            }
            .padding(16)
        }
    }
}

/// What a list shows until its first load has answered, so the page never looks empty or frozen.
struct LoadingRow: View {
    var body: some View {
        ProgressView().tint(Theme.primary)
            .frame(maxWidth: .infinity).padding(.top, 60)
            .accessibilityLabel("Chargement")
    }
}

/// A round image (channel avatar, or a stand-in with the initial).
struct AvatarView: View {
    let path: String?
    let name: String
    let api: RatonAPI
    var size: CGFloat = 56

    var body: some View {
        ZStack {
            Theme.surfaceMuted
            if let path {
                AsyncImage(url: api.url(path)) { image in
                    image.resizable().scaledToFill()
                } placeholder: { Color.clear }
            } else {
                Text(String(name.prefix(1)).uppercased())
                    .font(.raton(size * 0.4, .bold)).foregroundStyle(Theme.textMuted)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
    }
}

/// A white edge-to-edge row with the hairline under it, as the web's lists.
struct ListRow<Content: View>: View {
    var tint: Color? = nil
    @ViewBuilder let content: Content
    var body: some View {
        content
            .padding(.horizontal, 16).padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(tint == nil ? Theme.surface : Theme.tint)
            .overlay(alignment: .bottom) { Theme.border.frame(height: 1) }
    }
}

/// The web's "Fiches affichées" switch: the list shows everything, or leaves out the Vu and Indésirée fiches.
struct HideToggle: View {
    @Binding var showAll: Bool

    var body: some View {
        HStack(spacing: 2) {
            ForEach([(true, "list.bullet", "Tout voir"), (false, "eye.slash", "Masquer les fiches vues")], id: \.0) { option in
                let active = showAll == option.0
                Button { showAll = option.0 } label: {
                    Image(systemName: option.1).font(.system(size: 17))
                        .foregroundStyle(active ? Theme.primary : Theme.textMuted)
                        .frame(width: 44, height: 38)
                        .background(Capsule().fill(active ? Color.white : Color.clear))
                }
                .accessibilityLabel(option.2)
            }
        }
        .padding(4)
        .sandTrack()
        .sensoryFeedback(.selection, trigger: showAll)
    }
}

extension View {
    /// A text field as the web draws it: white, thin border, 10 pt corners.
    func webField() -> some View {
        padding(.horizontal, 14).padding(.vertical, 11)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color.white))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.border, lineWidth: 1))
    }
}

/// The system's own video player (AVPlayerViewController), with its native controls: play, seek,
/// Picture in Picture and the full-screen button, which rotates to landscape.
struct NativeVideoPlayer: UIViewControllerRepresentable {
    let player: AVPlayer

    func makeUIViewController(context: Context) -> AVPlayerViewController {
        let controller = AVPlayerViewController()
        controller.player = player
        controller.showsPlaybackControls = true
        controller.videoGravity = .resizeAspect
        controller.allowsPictureInPicturePlayback = true
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: AVPlayerViewController, context: Context) {
        if controller.player !== player { controller.player = player }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    /// Entering or leaving full screen moves the player view to another controller, which makes
    /// `AVPlayerViewController` pause, sometimes after the transition has ended. A video that was playing
    /// is started again whenever it pauses during the transition and the second after it; a pause the
    /// user asks for later is left alone.
    final class Coordinator: NSObject, AVPlayerViewControllerDelegate {
        private var observation: NSKeyValueObservation?
        private var guardUntil = Date.distantPast
        private var wasPlaying = false

        func playerViewController(_ controller: AVPlayerViewController,
                                  willBeginFullScreenPresentationWithAnimationCoordinator coordinator: UIViewControllerTransitionCoordinator) {
            keepPlaying(controller, through: coordinator)
        }

        func playerViewController(_ controller: AVPlayerViewController,
                                  willEndFullScreenPresentationWithAnimationCoordinator coordinator: UIViewControllerTransitionCoordinator) {
            keepPlaying(controller, through: coordinator)
        }

        private func keepPlaying(_ controller: AVPlayerViewController, through coordinator: UIViewControllerTransitionCoordinator) {
            guard let player = controller.player else { return }
            wasPlaying = wasPlaying || player.timeControlStatus != .paused
            guardUntil = .distantFuture
            observation = player.observe(\.timeControlStatus) { [weak self] player, _ in
                guard let self, self.wasPlaying, Date() < self.guardUntil, player.timeControlStatus == .paused else { return }
                DispatchQueue.main.async { player.play() }
            }
            coordinator.animate(alongsideTransition: nil) { [weak self] _ in
                guard let self else { return }
                if self.wasPlaying { player.play() }
                self.guardUntil = Date().addingTimeInterval(1)
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.1) {
                    self.observation = nil
                    self.wasPlaying = false
                }
            }
        }
    }
}
