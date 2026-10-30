import SwiftUI

/// The video / audio switch of the top bar of a fiche and of a playlist (the two media can coexist).
struct MediaModePill: View {
    let mode: MediaKind
    let onSelect: (MediaKind) -> Void

    var body: some View {
        HStack(spacing: 4) {
            ForEach([MediaKind.video, MediaKind.audio], id: \.self) { kind in
                Button {
                    withAnimation(.spring(response: 0.38, dampingFraction: 0.86)) { onSelect(kind) }
                } label: {
                    Image(systemName: kind == .video ? "video" : "waveform")
                        .font(.system(size: 18))
                        .foregroundStyle(mode == kind ? Theme.primary : Theme.textMuted)
                        .frame(width: 58, height: 38)
                        .background(Capsule().fill(mode == kind ? Color.white : Color.clear))
                }
                .accessibilityLabel(kind == .video ? "Vidéo" : "Audio")
            }
        }
        .padding(4)
        .sandTrack()
    }
}

/// Video and audio side by side like the web's carousel: the slides follow the finger, then settle on the
/// nearer one. On the video only the upper part starts a swipe, so the native player keeps its seek bar.
struct MediaPager<Video: View, Audio: View>: View {
    let mode: MediaKind
    let onSelect: (MediaKind) -> Void
    @ViewBuilder let video: () -> Video
    @ViewBuilder let audio: () -> Audio
    @State private var drag: CGFloat = 0
    @State private var dragging = false

    var body: some View {
        Color.clear
            .aspectRatio(16 / 9, contentMode: .fit)
            .overlay {
                GeometryReader { proxy in
                    let width = proxy.size.width
                    HStack(spacing: 0) {
                        video().frame(width: width, height: proxy.size.height)
                        audio().frame(width: width, height: proxy.size.height)
                    }
                    .offset(x: (mode == .audio ? -width : 0) + drag)
                    .simultaneousGesture(
                        DragGesture(minimumDistance: 12)
                            .onChanged { value in
                                let dx = value.translation.width
                                guard abs(dx) > abs(value.translation.height) || dragging else { return }
                                if !dragging {
                                    guard mode == .audio || value.startLocation.y < 160 else { return }
                                    dragging = true
                                }
                                // Rubber band past the first and last slides.
                                let blocked = (mode == .video && dx > 0) || (mode == .audio && dx < 0)
                                drag = blocked ? dx / 4 : dx
                            }
                            .onEnded { value in
                                guard dragging else { return }
                                let predicted = value.predictedEndTranslation.width
                                let goesToAudio = mode == .video && (value.translation.width < -width * 0.25 || predicted < -width * 0.5)
                                let goesToVideo = mode == .audio && (value.translation.width > width * 0.25 || predicted > width * 0.5)
                                withAnimation(.spring(response: 0.38, dampingFraction: 0.86)) {
                                    drag = 0
                                    if goesToAudio { onSelect(.audio) } else if goesToVideo { onSelect(.video) }
                                }
                                dragging = false
                            }
                    )
                }
            }
            .clipped()
    }
}
