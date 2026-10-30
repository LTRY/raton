import SwiftUI

/// The audios kept on the phone: they play without the server, and are removed here or from their fiche.
struct OfflineView: View {
    @EnvironmentObject private var state: AppState
    @EnvironmentObject private var player: PlayerController
    @EnvironmentObject private var offline: OfflineStore

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                PageHeader(title: "Hors ligne", back: true, badge: offline.items.count)
                if offline.items.isEmpty {
                    EmptyMessage(text: "Aucun audio sur ce téléphone. Depuis une fiche, « Écouter hors ligne » le garde ici.")
                }
                ForEach(offline.items) { item in
                    HStack(spacing: 12) {
                        Button {
                            if let api = state.api { player.playOffline(item, api: api) }
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(item.title).font(.raton(16, .semibold)).foregroundStyle(Theme.text).lineLimit(2)
                                if let channel = item.channel {
                                    Text(channel).font(.raton(14)).foregroundStyle(Theme.textMuted).lineLimit(1)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        Button { offline.remove(item.id) } label: { Image(systemName: "trash") }
                            .foregroundStyle(Theme.danger)
                            .frame(width: 44, height: 44)
                            .accessibilityLabel("Retirer \(item.title)")
                    }
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    Divider().padding(.leading, 16)
                }
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }
}
