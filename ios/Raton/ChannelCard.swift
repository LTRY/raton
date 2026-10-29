import SwiftUI

/// A channel of the Chaînes list, as on the web: banner with the avatar over it, name and number of
/// fiches, last activity, then the two cloches and the stars (they work from the list).
struct ChannelCard: View {
    let channel: ChannelItem
    let api: RatonAPI
    @State private var videosBell: Bool
    @State private var shortsBell: Bool
    @State private var rating: Int
    @State private var busy = false

    init(channel: ChannelItem, api: RatonAPI) {
        self.channel = channel
        self.api = api
        _videosBell = State(initialValue: channel.autoMetadataEnabled)
        _shortsBell = State(initialValue: channel.autoShortsEnabled)
        _rating = State(initialValue: channel.rating)
    }

    var body: some View {
        VStack(spacing: 0) {
            NavigationLink(value: channel) {
                VStack(alignment: .leading, spacing: 0) {
                    banner.frame(height: 96).frame(maxWidth: .infinity).clipped()
                    avatar.padding(.top, -36).padding(.leading, 16)
                    HStack(alignment: .top, spacing: 10) {
                        Text(channel.name).font(.raton(20, .bold)).foregroundStyle(Theme.text)
                            .lineLimit(2).multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                        Text("\(channel.videoCount)").font(.raton(13, .bold)).foregroundStyle(Theme.textSoft)
                            .padding(.horizontal, 10).padding(.vertical, 4)
                            .surface(in: Capsule())
                    }
                    .padding(.horizontal, 16).padding(.top, 10)
                    if let date = Format.frenchDate(channel.lastPlayedAt) {
                        Text("Dernière activité : \(date)").font(.raton(14)).foregroundStyle(Theme.textMuted)
                            .padding(.horizontal, 16).padding(.top, 6)
                    }
                    Color.clear.frame(height: 14)
                }
            }
            .buttonStyle(.plain)
            Theme.border.frame(height: 1)
            HStack(spacing: 10) {
                bell("videos", isOn: videosBell)
                bell("shorts", isOn: shortsBell)
                Spacer(minLength: 0)
                HStack(spacing: 3) {
                    ForEach(1...5, id: \.self) { star in
                        Button { Task { await setRating(star) } } label: {
                            Image(systemName: "star.fill").font(.system(size: 17))
                                .foregroundStyle(star <= rating ? Theme.amber : Theme.textFaint.opacity(0.55))
                        }
                        .accessibilityLabel("\(star) étoile\(star > 1 ? "s" : "")")
                    }
                    Button { Task { await setRating(0) } } label: {
                        Image(systemName: "xmark").font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.textFaint)
                    }
                    .padding(.leading, 2).accessibilityLabel("Retirer la note")
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
        }
        .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
        .surfaceCard(radius: 26)
        .padding(.horizontal, 16).padding(.vertical, 8)
    }

    @ViewBuilder
    private var banner: some View {
        if let path = channel.bannerUrl {
            AsyncImage(url: api.url(path)) { image in image.resizable().scaledToFill() } placeholder: { fallback }
        } else {
            fallback
        }
    }

    private var fallback: some View {
        LinearGradient(colors: [Color(hex: 0xE8A07A), Color(hex: 0xC2410C), Color(hex: 0x8A2C10)],
                       startPoint: .leading, endPoint: .trailing)
    }

    private var avatar: some View {
        ZStack {
            Circle().fill(Theme.surfaceMuted)
            if let path = channel.avatarUrl {
                AsyncImage(url: api.url(path)) { image in image.resizable().scaledToFill() } placeholder: { Color.clear }
                    .clipShape(Circle())
            } else {
                Text(String(channel.name.prefix(1)).uppercased()).font(.raton(28, .bold)).foregroundStyle(Theme.textSoft)
            }
        }
        .frame(width: 72, height: 72)
        .overlay(Circle().stroke(Color.white, lineWidth: 4))
        .shadow(color: Theme.shadow.opacity(0.15), radius: 6, y: 3)
    }

    private func bell(_ section: String, isOn: Bool) -> some View {
        Button { Task { await toggle(section, !isOn) } } label: {
            Image(systemName: isOn ? "bell.fill" : "bell.slash").font(.system(size: 17))
                .foregroundStyle(isOn ? Theme.primary : Theme.textMuted)
                .frame(width: 40, height: 40)
                .surface(in: RoundedRectangle(cornerRadius: 13, style: .continuous), tint: isOn ? Theme.primary : nil, interactive: true)
                .overlay(
                    RoundedRectangle(cornerRadius: 13, style: .continuous)
                        .stroke(isOn ? Theme.primary : Color.clear, lineWidth: 1.5))
                .overlay(alignment: .bottomTrailing) {
                    Image(systemName: section == "videos" ? "play.fill" : "rectangle.portrait")
                        .font(.system(size: 7, weight: .bold))
                        .foregroundStyle(isOn ? Theme.primary : Theme.textSoft)
                        .frame(width: 17, height: 17).background(Circle().fill(Color.white))
                        .overlay(Circle().stroke(isOn ? Theme.primary : Theme.textSoft, lineWidth: 1.2))
                        .offset(x: 5, y: 5)
                }
        }
        .padding(.trailing, 4)
        .disabled(busy)
        .accessibilityLabel("Suivi quotidien des \(section == "videos" ? "vidéos" : "shorts")")
        .accessibilityValue(isOn ? "activé" : "désactivé")
    }

    private func toggle(_ section: String, _ enable: Bool) async {
        busy = true
        defer { busy = false }
        if let reply: ChannelBellReply = try? await api.put(
            "/api/channels/\(channel.id)/bells/\(section)", body: ["enabled": enable]) {
            videosBell = reply.channel.autoMetadataEnabled
            shortsBell = reply.channel.autoShortsEnabled
        }
    }

    private func setRating(_ value: Int) async {
        let next = rating == value ? 0 : value
        if let _: ChannelState = try? await api.put("/api/channels/\(channel.id)/rating", body: ["rating": next]) {
            rating = next
        }
    }
}
