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
                .font(.raton(17, .medium))
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
        .padding(.horizontal, 16).padding(.vertical, 12)
        .glass(in: Capsule())
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

/// A glass card row, floating over the backdrop.
struct ListRow<Content: View>: View {
    var tint: Color? = nil
    @ViewBuilder let content: Content
    var body: some View {
        content
            .padding(.horizontal, 16).padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassCard(radius: 20, tint: tint)
            .padding(.horizontal, 12).padding(.vertical, 4)
    }
}
