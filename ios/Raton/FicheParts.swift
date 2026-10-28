import SwiftUI

// The panels under a fiche's player, the category chips and the sheets (categories, playlists).

/// Minimal Markdown for the notes the LLM writes: headings, bullets, and inline styles.
struct MarkdownText: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(text.components(separatedBy: "\n").enumerated()), id: \.offset) { _, line in
                if line.hasPrefix("#") {
                    Text(inline(line.drop(while: { $0 == "#" || $0 == " " })))
                        .font(.raton(18, .bold)).foregroundStyle(Theme.text).padding(.top, 8)
                } else if line.hasPrefix("- ") || line.hasPrefix("* ") {
                    HStack(alignment: .top, spacing: 8) {
                        Text("•")
                        Text(inline(line.dropFirst(2)))
                    }
                    .font(.raton(15)).foregroundStyle(Theme.textSoft)
                } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text(inline(Substring(line))).font(.raton(15)).foregroundStyle(Theme.textSoft)
                }
            }
        }
    }

    private func inline(_ text: Substring) -> AttributedString {
        (try? AttributedString(
            markdown: String(text),
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(String(text))
    }
}

/// Colored category labels; the colors come from `GET /api/categories`.
struct CategoryChips: View {
    let categories: [String]
    let api: RatonAPI
    @State private var styles: [CategoryStyle] = []

    var body: some View {
        HStack(spacing: 6) {
            ForEach(categories, id: \.self) { label in
                let color = styles.first { $0.label == label }.map { Color(hexString: $0.color) } ?? Theme.textMuted
                Text(label)
                    .font(.raton(13, .semibold)).foregroundStyle(color)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(Capsule().fill(color.opacity(0.12)))
            }
        }
        .task { styles = (try? await api.get("/api/categories")) ?? [] }
    }
}

/// Pick the categories of a fiche (or a channel, a playlist) among the user's labels.
struct CategoryPickerSheet: View {
    let api: RatonAPI
    @State var selected: [String]
    let onSave: ([String]) async -> Void
    @State private var styles: [CategoryStyle] = []
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(styles, id: \.label) { style in
                        Button {
                            if let index = selected.firstIndex(of: style.label) {
                                selected.remove(at: index)
                            } else {
                                selected.append(style.label)
                            }
                        } label: {
                            ListRow {
                                HStack {
                                    Circle().fill(Color(hexString: style.color)).frame(width: 12, height: 12)
                                    Text(style.label).font(.raton(17, .semibold)).foregroundStyle(Theme.text)
                                    Spacer()
                                    if selected.contains(style.label) {
                                        Image(systemName: "checkmark").foregroundStyle(Theme.primary)
                                    }
                                }
                            }
                        }
                    }
                    if styles.isEmpty {
                        EmptyMessage(text: "Aucune catégorie. Elles se créent dans les paramètres de Raton.")
                    }
                }
            }
            .ratonPage()
            .navigationTitle("Catégories")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Enregistrer") {
                        Task {
                            await onSave(selected)
                            dismiss()
                        }
                    }
                }
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() } }
            }
        }
        .task { styles = (try? await api.get("/api/categories")) ?? [] }
    }
}

/// Add the fiche to a playlist, remove it from one, or start a new playlist with it.
struct PlaylistsSheet: View {
    let api: RatonAPI
    let detail: VideoDetail
    let onChange: () async -> Void
    @State private var playlists: [PlaylistSummary] = []
    @State private var memberships: [VideoPlaylistRef] = []
    @State private var newTitle = ""
    @State private var errorMessage: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ErrorMessage(text: errorMessage)
                    ForEach(playlists) { playlist in
                        let member = memberships.first { $0.playlistId == playlist.id }
                        Button { Task { await toggle(playlist, member) } } label: {
                            ListRow {
                                HStack {
                                    Text(playlist.title).font(.raton(17, .semibold)).foregroundStyle(Theme.text)
                                    Spacer()
                                    Image(systemName: member == nil ? "plus.circle" : "checkmark.circle.fill")
                                        .foregroundStyle(member == nil ? Theme.textMuted : Theme.primary)
                                }
                            }
                        }
                    }
                    HStack {
                        TextField("Nouvelle playlist", text: $newTitle).font(.raton(17))
                        Button("Créer") { Task { await create() } }
                            .disabled(newTitle.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                    .padding(16)
                }
            }
            .ratonPage()
            .navigationTitle("Playlists")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Fermer") { dismiss() } } }
        }
        .task { await load() }
    }

    private func load() async {
        do {
            playlists = try await api.get("/api/playlists")
            let fresh: VideoDetail = try await api.get("/api/videos/\(detail.id)")
            memberships = fresh.playlists
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func toggle(_ playlist: PlaylistSummary, _ member: VideoPlaylistRef?) async {
        do {
            if let member {
                try await api.delete("/api/playlists/\(playlist.id)/items/\(member.itemId)")
            } else {
                let _: PlaylistDetail = try await api.post(
                    "/api/playlists/\(playlist.id)/items", body: ["video_id": detail.id])
            }
            await load()
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func create() async {
        do {
            let created: PlaylistSummary = try await api.post(
                "/api/playlists", body: ["title": newTitle])
            let _: PlaylistDetail = try await api.post(
                "/api/playlists/\(created.id)/items", body: ["video_id": detail.id])
            newTitle = ""
            await load()
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: Panels

struct InfoPanel: View {
    let detail: VideoDetail
    let seek: (Double) -> Void

    private func count(_ value: Int?, _ label: String) -> String? {
        value.map { "\($0.formatted(.number.locale(Locale(identifier: "fr_FR")))) \(label)" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let uploader = detail.metadata.uploader {
                Text(uploader).font(.raton(15, .semibold)).foregroundStyle(Theme.textSoft)
            }
            let figures = [count(detail.metadata.viewCount, "vues"), count(detail.metadata.likeCount, "j'aime"),
                           count(detail.metadata.commentCount, "commentaires")].compactMap { $0 }
            if !figures.isEmpty {
                Text(figures.joined(separator: " · ")).font(.raton(14)).foregroundStyle(Theme.textMuted)
            }
            Text(detail.metadata.description ?? "Pas de description.")
                .font(.raton(15)).foregroundStyle(Theme.textSoft)
            if !detail.metadata.tags.isEmpty {
                Text(detail.metadata.tags.map { "#\($0)" }.joined(separator: " "))
                    .font(.raton(13)).foregroundStyle(Theme.textMuted)
            }
            if !detail.metadata.chapters.isEmpty {
                Text("Chapitres").font(.raton(16, .bold)).foregroundStyle(Theme.text).padding(.top, 4)
                ForEach(Array(detail.metadata.chapters.enumerated()), id: \.offset) { _, chapter in
                    Button {
                        if let start = chapter.startSeconds { seek(start) }
                    } label: {
                        HStack {
                            Text(Format.clock(chapter.startSeconds ?? 0)).monospacedDigit()
                                .foregroundStyle(Theme.primary)
                            Text(chapter.title).foregroundStyle(Theme.textSoft)
                            Spacer(minLength: 0)
                        }
                        .font(.raton(15))
                    }
                }
            }
            if !detail.playlists.isEmpty {
                Text("Playlists : " + detail.playlists.map(\.title).joined(separator: ", "))
                    .font(.raton(14)).foregroundStyle(Theme.textMuted)
            }
        }
    }
}

struct SegmentsPanel: View {
    let detail: VideoDetail
    let seek: (Double) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(detail.sponsorSkipEnabled
                ? "Le lecteur saute ces segments."
                : "Le saut automatique est désactivé dans les paramètres de Raton.")
                .font(.raton(14)).foregroundStyle(Theme.textMuted)
            if detail.sponsorSegments.isEmpty {
                Text("Aucun segment détecté.").font(.raton(15)).foregroundStyle(Theme.textSoft)
            }
            ForEach(Array(detail.sponsorSegments.enumerated()), id: \.offset) { _, segment in
                Button { seek(segment.startSeconds) } label: {
                    HStack {
                        Text(segment.category).font(.raton(15, .semibold)).foregroundStyle(Theme.text)
                        Spacer()
                        Text("\(Format.clock(segment.startSeconds)) – \(Format.clock(segment.endSeconds))")
                            .font(.raton(14)).monospacedDigit().foregroundStyle(Theme.textMuted)
                    }
                }
            }
        }
    }
}

struct TranscriptPanel: View {
    let detail: VideoDetail
    let seek: (Double) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !detail.transcriptLines.isEmpty {
                ForEach(Array(detail.transcriptLines.enumerated()), id: \.offset) { _, line in
                    Button { seek(line.startSeconds) } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Text(Format.clock(line.startSeconds)).monospacedDigit()
                                .foregroundStyle(Theme.primary)
                            Text(line.text).foregroundStyle(Theme.textSoft).multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                        }
                        .font(.raton(15))
                    }
                }
            } else if let transcript = detail.documents.transcript {
                Text(transcript).font(.raton(15)).foregroundStyle(Theme.textSoft)
            } else {
                Text("Transcript indisponible.").font(.raton(15)).foregroundStyle(Theme.textMuted)
            }
        }
    }
}

struct NotesPanel: View {
    let detail: VideoDetail
    let generating: Bool
    let generate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let summary = detail.documents.shortSummary {
                Text(summary).font(.raton(16, .semibold)).foregroundStyle(Theme.text)
            }
            if let notes = detail.documents.notes {
                MarkdownText(text: notes)
            }
            Button(generating ? "Génération…" : "Régénérer les notes", action: generate)
                .buttonStyle(SandButtonStyle())
                .disabled(generating || !detail.hasTranscript)
        }
    }
}

struct CommentPanel: View {
    let initial: String
    let save: (String) async -> Void
    @State private var text = ""
    @State private var saving = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextEditor(text: $text)
                .font(.raton(16))
                .frame(minHeight: 140)
                .scrollContentBackground(.hidden)
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.white))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.border, lineWidth: 1))
            Button(saving ? "Enregistrement…" : "Enregistrer") {
                saving = true
                Task {
                    await save(text)
                    saving = false
                }
            }
            .buttonStyle(SandButtonStyle(active: text != initial))
            .disabled(saving || text == initial)
        }
        .onAppear { text = initial }
    }
}

/// The discussion about one fiche (`POST /api/videos/{id}/chat`, then the job is polled).
struct ChatPanel: View {
    let api: RatonAPI
    let detail: VideoDetail
    let onChange: () async -> Void
    @State private var question = ""
    @State private var pending: String?
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(detail.documents.chatMessages.enumerated()), id: \.offset) { _, message in
                bubble(message.content, mine: message.role == "user")
            }
            if let pending {
                bubble(pending, mine: true)
                Text("Raton réfléchit…").font(.raton(14)).foregroundStyle(Theme.textMuted)
            }
            if detail.documents.chatMessages.isEmpty && pending == nil {
                ForEach(detail.documents.suggestedQuestions, id: \.self) { suggestion in
                    Button(suggestion) { Task { await ask(suggestion) } }
                        .buttonStyle(SandButtonStyle())
                }
            }
            ErrorMessage(text: errorMessage)
            HStack {
                TextField("Poser une question sur cette fiche", text: $question, axis: .vertical)
                    .font(.raton(16))
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(Capsule().fill(Color.white))
                    .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
                Button {
                    let asked = question
                    question = ""
                    Task { await ask(asked) }
                } label: {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: 32)).foregroundStyle(Theme.primary)
                }
                .disabled(question.trimmingCharacters(in: .whitespaces).isEmpty || pending != nil)
            }
            if !detail.documents.chatMessages.isEmpty {
                Button("Effacer la discussion") { Task { await clear() } }
                    .font(.raton(14)).foregroundStyle(Theme.textMuted)
            }
        }
    }

    private func bubble(_ text: String, mine: Bool) -> some View {
        Text(text)
            .font(.raton(15)).foregroundStyle(mine ? .white : Theme.text)
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 14).fill(mine ? Theme.primary : Color.white))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(mine ? Color.clear : Theme.border, lineWidth: 1))
            .frame(maxWidth: .infinity, alignment: mine ? .trailing : .leading)
    }

    private func ask(_ text: String) async {
        errorMessage = nil
        pending = text
        do {
            let job: QueuedJob = try await api.post("/api/videos/\(detail.id)/chat", body: ["question": text])
            _ = try await api.waitForLLMJob(job.jobId)
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
        pending = nil
    }

    private func clear() async {
        do {
            try await api.delete("/api/videos/\(detail.id)/chat")
            await onChange()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
