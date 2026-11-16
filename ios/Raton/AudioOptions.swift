import SwiftUI

/// The two options of an audio, under its seek bar: the speed and the sleep timer. Both belong to the
/// player, not to the fiche: they stay as they are from one audio to the next.
struct AudioOptionsRow: View {
    @EnvironmentObject private var player: PlayerController

    private static let delays = [15, 30, 45, 60]

    var body: some View {
        HStack(spacing: 10) {
            Menu {
                ForEach(PlayerController.rates, id: \.self) { rate in
                    Button { player.audioRate = rate } label: {
                        if player.audioRate == rate {
                            Label(Self.rateLabel(rate), systemImage: "checkmark")
                        } else {
                            Text(Self.rateLabel(rate))
                        }
                    }
                }
            } label: {
                pill("speedometer", Self.rateLabel(player.audioRate), active: player.audioRate != 1)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Vitesse de lecture : \(Self.rateLabel(player.audioRate))")
            Menu {
                ForEach(Self.delays, id: \.self) { minutes in
                    Button("Dans \(minutes) min") {
                        player.sleepTimer = .at(Date().addingTimeInterval(Double(minutes) * 60))
                    }
                }
                Button("À la fin de la piste") { player.sleepTimer = .endOfTrack }
                if player.sleepTimer != nil {
                    Divider()
                    Button("Désactiver le minuteur", role: .destructive) { player.sleepTimer = nil }
                }
            } label: {
                pill("moon", sleepLabel, active: player.sleepTimer != nil)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Minuteur de sommeil : \(sleepLabel)")
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 16).padding(.top, 6)
        .sensoryFeedback(.selection, trigger: player.audioRate)
        .sensoryFeedback(.selection, trigger: player.sleepTimer)
    }

    private var sleepLabel: String {
        switch player.sleepTimer {
        case .at(let date): return "Arrêt à \(Self.hour.string(from: date))"
        case .endOfTrack: return "Arrêt en fin de piste"
        case nil: return "Minuteur"
        }
    }

    private func pill(_ symbol: String, _ text: String, active: Bool) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).font(.system(size: 14, weight: .semibold))
            Text(text).font(.raton(14, .bold)).lineLimit(1)
        }
        .foregroundStyle(active ? Theme.primary : Theme.textSoft)
        .padding(.horizontal, 14).frame(height: 44)
        .surface(in: Capsule(), tint: active ? Theme.primary : nil, interactive: true)
    }

    /// "1×", "1,5×": the French decimal comma.
    static func rateLabel(_ rate: Float) -> String {
        let text = rate == rate.rounded() ? String(Int(rate)) : String(rate).replacingOccurrences(of: ".", with: ",")
        return text + "×"
    }

    private static let hour: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()
}

/// Why the loaded file does not play, with a button that loads it again.
struct PlaybackErrorMessage: View {
    @EnvironmentObject private var player: PlayerController
    let retry: () -> Void

    var body: some View {
        ErrorMessage(text: player.playbackError, retry: retry)
    }
}
