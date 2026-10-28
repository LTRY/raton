import SwiftUI

/// The Bibliothèque's filters, sent as the query of `GET /api/library`; the back applies them.
struct LibraryFilters: Equatable {
    var sort = "imported"
    var assets: Set<String> = []
    var excludedAssets: Set<String> = []
    var categories: Set<String> = []
    var excludedCategories: Set<String> = []
    var rated = false
    // False: the back's default, which leaves out the Vu and Indésirée fiches; true: "Tout voir".
    var showAll = false
    var uncategorized = false
    var assetMode = "or"
    var categoryMode = "or"
    var section = "videos"

    var isDefault: Bool { self == LibraryFilters() }

    /// What the "Filtres" pill counts and the pills under it list: (label, kind, remove).
    var activePills: [(label: String, excluded: Bool, remove: (inout LibraryFilters) -> Void)] {
        var pills: [(label: String, excluded: Bool, remove: (inout LibraryFilters) -> Void)] = []
        for value in assets.sorted() { pills.append((Self.assetLabel(value), false, { $0.assets.remove(value) })) }
        for value in excludedAssets.sorted() { pills.append((Self.assetLabel(value), true, { $0.excludedAssets.remove(value) })) }
        for value in categories.sorted() { pills.append((value, false, { $0.categories.remove(value) })) }
        for value in excludedCategories.sorted() { pills.append((value, true, { $0.excludedCategories.remove(value) })) }
        if rated { pills.append(("Notées", false, { $0.rated = false })) }
        if uncategorized { pills.append(("Sans catégorie", false, { $0.uncategorized = false })) }
        return pills
    }

    private static func assetLabel(_ kind: String) -> String {
        ["video": "Vidéo", "audio": "Audio", "shorts": "Shorts", "metadata": "Métadonnées",
         "transcript": "Transcript", "imported": "Manuelles", "notes": "Notes"][kind] ?? kind
    }

    var queryItems: [URLQueryItem] {
        var items = [URLQueryItem(name: "sort", value: sort), URLQueryItem(name: "section", value: section)]
        items += assets.sorted().map { URLQueryItem(name: "asset", value: $0) }
        items += excludedAssets.sorted().map { URLQueryItem(name: "exclude_asset", value: $0) }
        items += categories.sorted().map { URLQueryItem(name: "category", value: $0) }
        items += excludedCategories.sorted().map { URLQueryItem(name: "exclude_category", value: $0) }
        if rated { items.append(URLQueryItem(name: "rated", value: "true")) }
        if showAll { items.append(URLQueryItem(name: "hide", value: "none")) }
        if uncategorized { items.append(URLQueryItem(name: "uncategorized", value: "true")) }
        items.append(URLQueryItem(name: "asset_filter_mode", value: assetMode))
        items.append(URLQueryItem(name: "category_filter_mode", value: categoryMode))
        return items
    }

    mutating func apply(_ view: SavedView) {
        assets = Set(view.assets)
        excludedAssets = Set(view.excludedAssets)
        categories = Set(view.categories)
        excludedCategories = Set(view.excludedCategories)
        rated = view.rated
        assetMode = view.assetFilterMode
        categoryMode = view.categoryFilterMode
    }
}

/// A chip that goes unset → included → excluded as it is tapped, like the web's three-state chips.
private struct TriStateChip: View {
    let title: String
    @Binding var included: Set<String>
    @Binding var excluded: Set<String>
    let value: String

    var body: some View {
        let isIncluded = included.contains(value)
        let isExcluded = excluded.contains(value)
        Button {
            if isIncluded {
                included.remove(value); excluded.insert(value)
            } else if isExcluded {
                excluded.remove(value)
            } else {
                included.insert(value)
            }
        } label: {
            Text((isExcluded ? "≠ " : "") + title)
        }
        .buttonStyle(SandButtonStyle(active: isIncluded || isExcluded, fill: false))
    }
}

struct LibraryFiltersSheet: View {
    let api: RatonAPI
    @State var filters: LibraryFilters
    let onApply: (LibraryFilters) -> Void
    @State private var styles: [CategoryStyle] = []
    @State private var views: [SavedView] = []
    @Environment(\.dismiss) private var dismiss

    private static let sorts = [
        ("imported", "Import récent"), ("published", "Publication récente"),
        ("views", "Les plus vues"), ("rated", "Les mieux notées"),
    ]
    private static let assetKinds = [
        ("video", "Vidéo"), ("audio", "Audio"), ("metadata", "Métadonnées"),
        ("transcript", "Transcript"), ("imported", "Importé"), ("shorts", "Shorts"),
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if !views.isEmpty {
                        section("Vues enregistrées") {
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack {
                                    ForEach(views, id: \.name) { view in
                                        Button(view.name) { filters.apply(view) }
                                            .buttonStyle(SandButtonStyle(fill: false))
                                    }
                                }
                            }
                        }
                    }
                    section("Trier") {
                        Picker("", selection: $filters.sort) {
                            ForEach(Self.sorts, id: \.0) { Text($0.1).tag($0.0) }
                        }
                        .pickerStyle(.menu).tint(Theme.primary)
                    }
                    section("Section") {
                        Picker("", selection: $filters.section) {
                            Text("Vidéos").tag("videos")
                            Text("Shorts").tag("shorts")
                        }
                        .pickerStyle(.segmented)
                    }
                    section("Fichiers") {
                        modePicker($filters.assetMode)
                        chips {
                            ForEach(Self.assetKinds, id: \.0) { kind in
                                TriStateChip(title: kind.1, included: $filters.assets,
                                             excluded: $filters.excludedAssets, value: kind.0)
                            }
                            Toggle("★ Notées", isOn: $filters.rated).toggleStyle(.button).tint(Theme.primary)
                        }
                    }
                    if !styles.isEmpty {
                        section("Catégories") {
                            modePicker($filters.categoryMode)
                            chips {
                                ForEach(styles, id: \.label) { style in
                                    TriStateChip(title: style.label, included: $filters.categories,
                                                 excluded: $filters.excludedCategories, value: style.label)
                                }
                                Toggle("Sans catégorie", isOn: $filters.uncategorized).toggleStyle(.button).tint(Theme.primary)
                            }
                        }
                    }
                    Toggle("Tout voir (Vu et Indésirée compris)", isOn: $filters.showAll)
                        .font(.raton(16, .medium)).tint(Theme.primary)
                }
                .padding(16)
            }
            .ratonPage()
            .navigationTitle("Filtres")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Appliquer") { onApply(filters); dismiss() }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Réinitialiser") { filters = LibraryFilters() }
                }
            }
        }
        .task {
            styles = (try? await api.get("/api/categories")) ?? []
            views = (try? await api.get("/api/library/views")) ?? []
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.raton(16, .bold)).foregroundStyle(Theme.text)
            content()
        }
    }

    private func modePicker(_ binding: Binding<String>) -> some View {
        Picker("", selection: binding) {
            Text("Un des").tag("or")
            Text("Tous les").tag("and")
        }
        .pickerStyle(.segmented)
    }

    private func chips<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        FlowLayout(spacing: 8) { content() }
    }
}

/// Wraps its children onto several lines, like the web's chip rows.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(proposal.width ?? 320, subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(bounds.width, subviews)
        for (index, origin) in result.origins.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y), proposal: .unspecified)
        }
    }

    private func arrange(_ width: CGFloat, _ subviews: Subviews) -> (size: CGSize, origins: [CGPoint]) {
        var origins: [CGPoint] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, maxX: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { x = 0; y += rowHeight + spacing; rowHeight = 0 }
            origins.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            maxX = max(maxX, x - spacing)
            rowHeight = max(rowHeight, size.height)
        }
        return (CGSize(width: maxX, height: y + rowHeight), origins)
    }
}
