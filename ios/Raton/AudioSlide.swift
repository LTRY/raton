import SwiftUI

/// The audio side of a fiche, as the web's phone layout draws it (`.media-slide-audio`): a 16:9 card on
/// a terracotta-to-brown radial gradient, the cover square in the middle with the glass play (or
/// download) disc on it and ±15 s on either side.
struct AudioSlide: View {
    let detail: VideoDetail
    let api: RatonAPI
    let downloading: Bool
    let onDownload: () -> Void
    @EnvironmentObject private var player: PlayerController

    private var hasFile: Bool { detail.mediaUrls.audio != nil }
    private var loaded: Bool { player.track?.videoID == detail.id && player.track?.kind == .audio }
    private var playing: Bool { loaded && player.isPlaying }

    var body: some View {
        ZStack {
            AudioStageBackground()
            cover
            HStack(spacing: 70) {
                skip(-15, "gobackward.15")
                disc
                skip(15, "goforward.15")
            }
            Text(label).font(.raton(12, .bold)).foregroundStyle(Color(hex: 0xF4EAD9))
                .shadow(color: .black.opacity(0.6), radius: 2, y: 1)
                .frame(maxHeight: .infinity, alignment: .center).offset(y: 40 + 12)
                .opacity(label.isEmpty ? 0 : 1)
        }
        .aspectRatio(16 / 9, contentMode: .fit)
        .clipped()
    }

    private var label: String {
        if downloading { return "Téléchargement…" }
        if !hasFile && detail.filesPurged { return "Fichiers supprimés" }
        return ""
    }

    private var cover: some View {
        AudioCover(videoID: detail.id, hasThumbnail: detail.mediaUrls.thumbnail != nil, api: api)
    }

    @ViewBuilder
    private var disc: some View {
        if hasFile {
            glassDisc(playing ? "pause.fill" : "play.fill", playing ? "Pause" : "Lecture") {
                if loaded { player.togglePlayPause() } else { player.play(detail: detail, kind: .audio, api: api) }
            }
        } else if downloading {
            ProgressView().tint(.white)
                .frame(width: 64, height: 64)
                .background(Circle().fill(Color.white.opacity(0.16)))
        } else if !detail.filesPurged {
            glassDisc("arrow.down.to.line", "Télécharger l'audio", action: onDownload)
        } else {
            glassDisc("arrow.down.to.line", "Retélécharger l'audio", action: onDownload)
        }
    }

    private func glassDisc(_ symbol: String, _ label: String, action: @escaping () -> Void) -> some View {
        GlassDiscButton(symbol: symbol, label: label, action: action)
    }

    @ViewBuilder
    private func skip(_ seconds: Double, _ symbol: String) -> some View {
        Button { player.skip(by: seconds) } label: {
            Image(systemName: symbol).font(.system(size: 18)).foregroundStyle(Color(hex: 0xF4EAD9))
                .frame(width: 44, height: 44)
                .background(Circle().fill(Color.white.opacity(0.12)))
        }
        .opacity(hasFile ? 1 : 0)
        .disabled(!hasFile)
        .accessibilityLabel(seconds < 0 ? "Reculer de 15 secondes" : "Avancer de 15 secondes")
    }
}

/// The terracotta-to-brown radial gradient behind the cover of an audio stage.
struct AudioStageBackground: View {
    var body: some View {
        RadialGradient(colors: [Color(hex: 0x9A3412), Theme.text], center: UnitPoint(x: 0.2, y: 0.4),
                       startRadius: 0, endRadius: 330)
    }
}

/// The 168 pt square cover of an audio stage: the thumbnail, or a brown square without one.
struct AudioCover: View {
    let videoID: Int?
    let hasThumbnail: Bool
    let api: RatonAPI
    /// 168 pt on a fiche; a playlist's stage shrinks it to leave a row of controls under it.
    var size: CGFloat = 168

    var body: some View {
        ZStack {
            if let videoID, hasThumbnail {
                Color.clear
                    .overlay { Thumbnail(videoID: videoID, hasThumbnail: true, api: api) }
                    .clipped()
            } else {
                Color(hex: 0x3A2A1E)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: 22 * size / 168, style: .continuous))
        .shadow(color: Color(hex: 0x2B2018).opacity(0.35), radius: 14, y: 12)
    }
}

/// The 64 pt glass disc of an audio stage (play, pause, download).
struct GlassDiscButton: View {
    let symbol: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 24, weight: .semibold)).foregroundStyle(.white)
                .frame(width: 64, height: 64)
                .background(.ultraThinMaterial, in: Circle())
                .background(Circle().fill(Color.white.opacity(0.16)))
                .overlay(Circle().stroke(Color.white.opacity(0.5), lineWidth: 1))
                .shadow(color: .black.opacity(0.28), radius: 12, y: 8)
        }
        .accessibilityLabel(label)
    }
}

/// The web's progress bar under the player: a thin track, the terracotta fill, a 4×22 playhead,
/// a time bubble while dragging and the two times below. Inert until this audio is the loaded track.
struct AudioSeekBar: View {
    let videoID: Int
    @EnvironmentObject private var player: PlayerController
    @State private var dragging = false
    @State private var dragPosition = 0.0

    private var active: Bool { player.track?.videoID == videoID && player.track?.kind == .audio }
    private var duration: Double { max(active ? player.duration : 0, 0) }
    private var position: Double { dragging ? dragPosition : (active ? player.position : 0) }
    private var progress: Double { duration > 0 ? min(max(position / duration, 0), 1) : 0 }

    var body: some View {
        VStack(spacing: 0) {
            GeometryReader { proxy in
                let width = proxy.size.width - 32
                ZStack(alignment: .topLeading) {
                    Capsule().fill(Color(hex: 0x2B2018).opacity(0.18))
                        .frame(width: width, height: 6).offset(x: 16, y: 19)
                    Capsule().fill(Theme.primary)
                        .frame(width: width * progress, height: 6).offset(x: 16, y: 19)
                    RoundedRectangle(cornerRadius: 2).fill(Theme.text)
                        .frame(width: 4, height: 22)
                        .scaleEffect(x: dragging ? 1.5 : 1, y: dragging ? 1.25 : 1)
                        .offset(x: 16 + width * progress - 2, y: 11)
                    if dragging {
                        Text(Format.clock(position)).font(.raton(15, .heavy)).monospacedDigit()
                            .foregroundStyle(Color(hex: 0xF4EAD9))
                            .frame(minWidth: 60, minHeight: 32)
                            .background(RoundedRectangle(cornerRadius: 10).fill(Theme.text))
                            .offset(x: min(max(16 + width * progress - 30, 0), proxy.size.width - 60), y: -34)
                    }
                }
                .contentShape(Rectangle())
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            guard active, duration > 0 else { return }
                            dragging = true
                            dragPosition = min(max((value.location.x - 16) / width, 0), 1) * duration
                        }
                        .onEnded { _ in
                            if dragging { player.seek(to: dragPosition) }
                            dragging = false
                        }
                )
            }
            .frame(height: 44)
            HStack {
                Text(Format.clock(position))
                Spacer()
                Text(active && duration > 0 ? Format.clock(duration) : "--:--")
            }
            .font(.raton(13, .semibold)).monospacedDigit().foregroundStyle(Color(hex: 0x5C4D3C))
            .padding(.horizontal, 16).padding(.top, -10)
        }
        .opacity(active ? 1 : 0.55)
        .padding(.top, 6)
    }
}
