import SwiftUI

/// The user's own settings (the web shows only these on a phone): who is using the app, screen time,
/// couvre-feu, the offline audios and the server this app talks to. Nothing here has a save button:
/// a switch, a stepper or a time saves itself shortly after it moves.
struct SettingsView: View {
    @EnvironmentObject private var state: AppState
    @ObservedObject private var offline = OfflineStore.shared
    @State private var users: [RatonUser] = []
    @State private var name = ""
    @State private var settings: UserSettings?
    @State private var screenTime: ScreenTimeReply?
    @State private var dailyMinutes: [String: Int] = [:]
    @State private var curfewOn = false
    @State private var curfewStart = Date()
    @State private var curfewEnd = Date()
    // What the back last confirmed, so that loading the page never counts as an edit.
    @State private var savedMinutes: [String: Int] = [:]
    @State private var savedCurfew = ""
    @State private var saveCount = 0
    @State private var errorMessage: String?
    @State private var showRename = false
    @State private var showUsers = false

    private static let kinds = [("video", "Vidéos"), ("short", "Shorts"), ("podcast", "Podcasts"), ("music", "Musique")]

    var body: some View {
        Group {
            if let api = state.api {
                ScrollView {
                    VStack(alignment: .leading, spacing: 26) {
                        PageHeader(title: "Paramètres")
                        profile(api)
                        ErrorMessage(text: errorMessage)
                        if settings != nil {
                            screenTimeSection
                            curfewSection
                        }
                        section("Sur ce téléphone") {
                            NavigationLink { OfflineView() } label: {
                                row("arrow.down.circle.fill", "Audios hors ligne", detail: "\(offline.items.count)")
                            }
                            divider
                            NavigationLink {
                                ServerURLView(title: "Serveur", back: true, onSaved: {})
                            } label: {
                                row("server.rack", "Serveur", detail: server)
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
                .barClearance()
                .task { await load(api) }
                .task(id: dailyMinutes) { await saveMinutes(api) }
                .task(id: curfewKey) { await saveCurfew(api) }
                .navigationDestination(isPresented: $showUsers) {
                    UserPickerView(title: "Utilisateurs", back: true, manage: true)
                }
                .alert("Renommer", isPresented: $showRename) {
                    TextField("Nom", text: $name)
                    Button("Annuler", role: .cancel) { name = currentName }
                    Button("Enregistrer") { Task { await rename(api) } }
                } message: {
                    Text("Le nom affiché pour cet utilisateur.")
                }
                .sensoryFeedback(.success, trigger: saveCount)
            }
        }
        .ratonPage()
        .toolbar(.hidden, for: .navigationBar)
    }

    private var currentName: String { users.first { $0.id == state.userID }?.name ?? "" }

    private var server: String {
        state.serverURL?.host() ?? state.serverURL?.absoluteString ?? ""
    }

    // MARK: Profile

    /// Who is using the app: the rename and the user switch hide behind one discreet menu.
    private func profile(_ api: RatonAPI) -> some View {
        HStack(spacing: 14) {
            AvatarView(path: nil, name: currentName, api: api, size: 60)
            Text(currentName).font(.raton(24, .bold)).foregroundStyle(Theme.text)
                .lineLimit(1).minimumScaleFactor(0.7)
            Spacer(minLength: 0)
            Menu {
                Button { name = currentName; showRename = true } label: { Label("Renommer", systemImage: "pencil") }
                Button { showUsers = true } label: { Label("Changer d'utilisateur", systemImage: "person.2") }
            } label: {
                Image(systemName: "ellipsis").font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.textSoft)
                    .frame(width: 40, height: 40).contentShape(Circle())
            }
            .accessibilityLabel("Profil")
        }
        .padding(.horizontal, 20)
    }

    // MARK: Screen time

    private var screenTimeSection: some View {
        section("Temps d'écran par jour") {
            ForEach(Array(Self.kinds.enumerated()), id: \.element.0) { index, kind in
                if index > 0 { divider }
                limitRow(kind)
            }
        }
    }

    private func limitRow(_ kind: (String, String)) -> some View {
        let minutes = dailyMinutes[kind.0] ?? 1
        let today = screenTime?.periods["today"]?[kind.0]
        return HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(kind.1).font(.raton(16, .semibold)).foregroundStyle(Theme.text)
                if let today {
                    Text("\(Int(today.seconds / 60)) min aujourd'hui").font(.raton(13)).foregroundStyle(Theme.textMuted)
                }
            }
            Spacer(minLength: 8)
            Text("\(minutes) min").font(.raton(15, .semibold)).monospacedDigit().foregroundStyle(Theme.textSoft)
            Stepper("", value: Binding(get: { minutes }, set: { dailyMinutes[kind.0] = $0 }), in: 1...1440, step: 5)
                .labelsHidden()
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
    }

    // MARK: Couvre-feu

    /// One line for the switch, a second one for the hours once it is on.
    private var curfewSection: some View {
        section("Couvre-feu") {
            VStack(spacing: 0) {
                Toggle(isOn: $curfewOn.animation()) {
                    Text("Bloquer la nuit").font(.raton(16, .semibold)).foregroundStyle(Theme.text)
                }
                .tint(Theme.primary)
                .padding(.horizontal, 16).padding(.vertical, 12)
                if curfewOn {
                    divider
                    HStack(spacing: 10) {
                        Text("De").font(.raton(15)).foregroundStyle(Theme.textMuted)
                        DatePicker("", selection: $curfewStart, displayedComponents: .hourAndMinute).labelsHidden()
                        Text("à").font(.raton(15)).foregroundStyle(Theme.textMuted)
                        DatePicker("", selection: $curfewEnd, displayedComponents: .hourAndMinute).labelsHidden()
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 16).padding(.vertical, 10)
                }
            }
        }
    }

    // MARK: Building blocks

    /// A small heading over one rounded card of rows.
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased()).font(.raton(12, .bold)).tracking(0.8).foregroundStyle(Theme.textMuted)
                .padding(.horizontal, 36)
            VStack(spacing: 0, content: content)
                .frame(maxWidth: .infinity, alignment: .leading)
                .surfaceCard(radius: 22)
                .padding(.horizontal, 16)
        }
    }

    private var divider: some View {
        Rectangle().fill(Theme.border.opacity(0.6)).frame(height: 1).padding(.leading, 62)
    }

    /// A navigation row: a tinted icon tile, the label and a quiet detail before the chevron.
    private func row(_ symbol: String, _ title: String, detail: String) -> some View {
        HStack(spacing: 14) {
            Image(systemName: symbol).font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                .frame(width: 30, height: 30)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Theme.primary))
            Text(title).font(.raton(16, .semibold)).foregroundStyle(Theme.text)
            Spacer(minLength: 8)
            Text(detail).font(.raton(14)).foregroundStyle(Theme.textMuted).lineLimit(1).truncationMode(.middle)
            Image(systemName: "chevron.right").font(.system(size: 12, weight: .bold)).foregroundStyle(Theme.textFaint)
        }
        .padding(.horizontal, 16).padding(.vertical, 13)
        .contentShape(Rectangle())
    }

    // MARK: Loading and saving

    private static func time(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    private static func parse(_ time: String) -> Date {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.date(from: time) ?? Date()
    }

    /// The couvre-feu as one comparable value: changes to any part restart the save task.
    private var curfewKey: String { "\(curfewOn)|\(Self.time(curfewStart))|\(Self.time(curfewEnd))" }

    private func load(_ api: RatonAPI) async {
        do {
            users = try await api.users().users
            name = currentName
            let loaded: UserSettings = try await api.get("/api/settings")
            dailyMinutes = loaded.screenTimeLimits.compactMapValues { $0["today"] }
            savedMinutes = dailyMinutes
            curfewOn = loaded.curfew.enabled
            curfewStart = Self.parse(loaded.curfew.start)
            curfewEnd = Self.parse(loaded.curfew.end)
            savedCurfew = curfewKey
            settings = loaded
            screenTime = try? await api.get("/api/screen-time")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func rename(_ api: RatonAPI) async {
        guard let id = state.userID, !name.trimmingCharacters(in: .whitespaces).isEmpty, name != currentName else { return }
        do {
            let _: RatonUser = try await api.put("/api/users/\(id)", body: ["name": name])
            users = try await api.users().users
            saveCount += 1
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Waits for the stepper to stop moving, then saves the limits.
    private func saveMinutes(_ api: RatonAPI) async {
        guard settings != nil, dailyMinutes != savedMinutes else { return }
        try? await Task.sleep(for: .milliseconds(700))
        guard !Task.isCancelled else { return }
        let sent = dailyMinutes
        if await save(api, ["screen_time_today_minutes": sent]) {
            savedMinutes = sent
            screenTime = try? await api.get("/api/screen-time")
        }
    }

    private func saveCurfew(_ api: RatonAPI) async {
        guard settings != nil, curfewKey != savedCurfew else { return }
        try? await Task.sleep(for: .milliseconds(500))
        guard !Task.isCancelled else { return }
        let sent = curfewKey
        if await save(api, ["curfew_enabled": curfewOn, "curfew_start": Self.time(curfewStart),
                            "curfew_end": Self.time(curfewEnd)]) {
            savedCurfew = sent
        }
    }

    private func save(_ api: RatonAPI, _ body: [String: Any]) async -> Bool {
        errorMessage = nil
        do {
            let _: UserSettings = try await api.put("/api/settings", body: body)
            saveCount += 1
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}
