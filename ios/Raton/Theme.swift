import SwiftUI

/// The look of the web front, in Liquid Glass: (`front/static/css/tailwind.input.css`, `@theme` and `:root` tokens):
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

// MARK: Liquid Glass

extension View {
    /// Liquid Glass: the system `glassEffect` on iOS 26 (needs the iOS 26 SDK, Xcode 26), a frosted
    /// material with a light rim before that. One entry point so every screen looks the same.
    @ViewBuilder
    func glass<S: Shape>(in shape: S, tint: Color? = nil, interactive: Bool = false) -> some View {
        #if compiler(>=6.2)
        if #available(iOS 26, *) {
            var effect = Glass.regular
            if let tint { effect = effect.tint(tint) }
            self.glassEffect(effect.interactive(interactive), in: shape)
        } else {
            frostedGlass(in: shape, tint: tint)
        }
        #else
        frostedGlass(in: shape, tint: tint)
        #endif
    }

    private func frostedGlass<S: Shape>(in shape: S, tint: Color?) -> some View {
        background {
            ZStack {
                shape.fill(.ultraThinMaterial)
                if let tint { shape.fill(tint.opacity(0.22)) }
            }
        }
        .overlay(
            shape.stroke(
                LinearGradient(colors: [.white.opacity(0.9), .white.opacity(0.25), .white.opacity(0.6)],
                               startPoint: .topLeading, endPoint: .bottomTrailing),
                lineWidth: 1))
        .shadow(color: Theme.shadow.opacity(0.10), radius: 14, y: 6)
    }

    /// A glass card with rounded corners, the container of rows and panels.
    func glassCard(radius: CGFloat = 22, tint: Color? = nil) -> some View {
        glass(in: RoundedRectangle(cornerRadius: radius, style: .continuous), tint: tint)
    }

    /// The warm backdrop the glass floats over, under the safe areas too. Glass needs something
    /// colorful behind it: a flat cream would make it invisible.
    func ratonPage() -> some View {
        background(GlassBackdrop().ignoresSafeArea())
    }
}

/// Cream gradient with soft terracotta, amber and rose lights, for the glass to refract.
struct GlassBackdrop: View {
    var body: some View {
        GeometryReader { proxy in
            ZStack {
                LinearGradient(colors: [Color(hex: 0xFFF6EA), Color(hex: 0xFCE7D6), Color(hex: 0xF9DCCB)],
                               startPoint: .top, endPoint: .bottom)
                Circle().fill(Theme.primary.opacity(0.30)).frame(width: 300)
                    .blur(radius: 70).position(x: proxy.size.width * 0.05, y: proxy.size.height * 0.12)
                Circle().fill(Theme.amber.opacity(0.32)).frame(width: 280)
                    .blur(radius: 70).position(x: proxy.size.width * 0.98, y: proxy.size.height * 0.40)
                Circle().fill(Color(hex: 0xF08A8A).opacity(0.28)).frame(width: 320)
                    .blur(radius: 80).position(x: proxy.size.width * 0.15, y: proxy.size.height * 0.88)
            }
        }
    }
}

/// A round glass button floating over the page (back, menu...).
struct CircleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.raton(17, .semibold))
            .foregroundStyle(Theme.text)
            .frame(width: 46, height: 46)
            .glass(in: Circle(), interactive: true)
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

/// The glass buttons under a fiche ("Plus d'informations", "Commentaire"); active ones are tinted.
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
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .glass(in: Capsule(), tint: active ? Theme.primary : nil, interactive: true)
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

/// The primary call to action: a glass pill tinted with the terracotta.
struct PillButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.raton(17, .semibold))
            .foregroundStyle(Theme.primary)
            .padding(.horizontal, 24)
            .padding(.vertical, 14)
            .glass(in: Capsule(), tint: Theme.primary, interactive: true)
            .opacity(configuration.isPressed ? 0.75 : 1)
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
                    .foregroundStyle(star <= rating ? Theme.amber : Theme.textFaint.opacity(0.55))
            }
        }
    }
}
