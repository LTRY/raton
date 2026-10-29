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

struct ErrorMessage: View {
    let text: String?
    var body: some View {
        if let text {
            Text(text).font(.raton(15, .medium)).foregroundStyle(Theme.danger).padding(16)
        }
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
