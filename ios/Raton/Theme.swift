import SwiftUI

/// The look of the web front (`front/static/css/tailwind.input.css`, `@theme` and `:root` tokens):
/// warm cream background, terracotta primary, Plus Jakarta Sans. Colors are copied from those
/// tokens; the app is light only, like the screens the tokens were drawn for.
enum Theme {
    static let bg = Color(hex: 0xFBF6EE)
    static let surface = Color.white
    static let surfaceMuted = Color(hex: 0xF4EAD9)
    static let text = Color(hex: 0x2B2018)
    static let textSoft = Color(hex: 0x5C4D3D)
    static let textMuted = Color(hex: 0x7A6A57)
    static let textFaint = Color(hex: 0xB9AA95)
    static let primary = Color(hex: 0xC2410C)
    static let border = Color(hex: 0xE9DFCF)
    static let borderStrong = Color(hex: 0xD8CBB6)
    static let tint = Color(hex: 0xFFF1E8)
    static let shadow = Color(hex: 0x7C2D12)
    static let amber = Color(hex: 0xF59E0B)
    static let player = Color(hex: 0x201811)
    static let danger = Color(hex: 0xDC2626)
}

extension Color {
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255)
    }
}

extension Color {
    /// "#rrggbb", as the API gives category colors; gray when it cannot be read.
    init(hexString: String) {
        let digits = hexString.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        self.init(hex: UInt32(digits, radix: 16) ?? 0x7A6A57)
    }
}

extension Font {
    /// Plus Jakarta Sans (variable font bundled in the app), at a fixed size.
    static func raton(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .custom("Plus Jakarta Sans", fixedSize: size).weight(weight)
    }
}

/// A round white button floating over the page (back, menu...), as on the web header.
struct CircleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.raton(17, .semibold))
            .foregroundStyle(Theme.text)
            .frame(width: 46, height: 46)
            .background(Circle().fill(Color.white))
            .overlay(Circle().stroke(Theme.border, lineWidth: 1))
            .shadow(color: Theme.shadow.opacity(0.12), radius: 8, y: 4)
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

/// The sand-colored buttons under a fiche ("Plus d'informations", "Commentaire").
struct SandButtonStyle: ButtonStyle {
    var active = false
    // False for a button that sits in a horizontal scroller: it keeps its own width.
    var fill = true

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.raton(16, .medium))
            .foregroundStyle(active ? Theme.primary : Theme.textSoft)
            .lineLimit(1)
            .frame(maxWidth: fill ? .infinity : nil)
            .padding(.horizontal, 12)
            .padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 8).fill(active ? Theme.tint : Theme.surfaceMuted))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

/// The primary call to action: white pill with terracotta text and a warm shadow.
struct PillButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.raton(17, .semibold))
            .foregroundStyle(Theme.primary)
            .padding(.horizontal, 24)
            .padding(.vertical, 14)
            .background(Capsule().fill(Color.white))
            .shadow(color: Theme.shadow.opacity(0.15), radius: 10, y: 5)
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct StarsView: View {
    let rating: Int
    var size: CGFloat = 14

    var body: some View {
        HStack(spacing: 2) {
            ForEach(1...5, id: \.self) { star in
                Image(systemName: "star.fill")
                    .font(.system(size: size))
                    .foregroundStyle(star <= rating ? Theme.amber : Color(hex: 0xF6E4DD))
            }
        }
    }
}

extension View {
    /// The cream page background, under the safe areas too.
    func ratonPage() -> some View {
        background(Theme.bg.ignoresSafeArea())
    }
}
