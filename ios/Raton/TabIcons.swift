import SwiftUI

/// The five icons of the bottom bar, drawn from the web's SVGs (`front/templates/base.html`, `.mobile-tabbar`)
/// with the animations of `front/static/css/tailwind.input.css` ("Bottom-bar icons"): each one plays when its
/// tab is tapped or becomes the active one, and holds still otherwise.
enum TabIconKind { case home, channels, library, playlists, settings }

struct TabIcon: View {
    let kind: TabIconKind
    let color: Color
    /// The bar behind the icon: the two knobs of the settings icon are filled with it to hide the line.
    let knob: Color
    /// Increments each time the animation must play.
    let trigger: Int
    var size: CGFloat = 26

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var start = Date.distantPast
    @State private var running = false

    var body: some View {
        TimelineView(.animation(paused: !running)) { context in
            let t = running ? context.date.timeIntervalSince(start) : 99
            Canvas { gfx, canvasSize in
                let k = canvasSize.width / 24
                var layer = gfx
                layer.scaleBy(x: k, y: k)
                TabIconDrawing.draw(kind, in: &layer, t: t, color: color, knob: knob, unit: k)
            }
        }
        .frame(width: size, height: size)
        .onChange(of: trigger) { _ in play() }
        .onAppear { if trigger > 0 { play() } }
    }

    private func play() {
        guard !reduceMotion else { return }
        start = Date()
        running = true
        Task {
            try? await Task.sleep(nanoseconds: 1_300_000_000)
            running = false
        }
    }
}

private enum TabIconDrawing {
    static func draw(_ kind: TabIconKind, in gfx: inout GraphicsContext, t: Double, color: Color, knob: Color, unit: CGFloat) {
        let style = StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round)
        func stroke(_ path: Path, _ context: GraphicsContext, opacity: Double = 1) {
            var c = context
            c.opacity = opacity
            c.stroke(path, with: .color(color), style: style)
        }
        switch kind {
        case .home:
            var path = Path()
            path.move(to: CGPoint(x: 3, y: 10.5)); path.addLine(to: CGPoint(x: 12, y: 3)); path.addLine(to: CGPoint(x: 21, y: 10.5))
            path.move(to: CGPoint(x: 5.5, y: 9)); path.addLine(to: CGPoint(x: 5.5, y: 20)); path.addLine(to: CGPoint(x: 10, y: 20))
            path.addLine(to: CGPoint(x: 10, y: 14.5)); path.addLine(to: CGPoint(x: 14, y: 14.5)); path.addLine(to: CGPoint(x: 14, y: 20))
            path.addLine(to: CGPoint(x: 18.5, y: 20)); path.addLine(to: CGPoint(x: 18.5, y: 9))
            // tab-hop: squash, jump, settle; origin at the top centre of the house.
            let p = clamp(t / 0.75)
            let frames: [(Double, Double, Double, Double)] = [
                (0, 0, 1, 1), (0.25, 1.0, 1.1, 0.88), (0.55, -2.4, 0.95, 1.08), (0.8, 0, 1.04, 0.96), (1, 0, 1, 1),
            ]
            let (ty, sx, sy) = keyframes(frames, p)
            var c = gfx
            c.translateBy(x: 12, y: 3 + ty); c.scaleBy(x: sx, y: sy); c.translateBy(x: -12, y: -3)
            stroke(path, c)
        case .channels:
            // tab-flick: the body flickers (steps), tab-draw: the antenna draws itself.
            let p = clamp(t / 0.9)
            let opacity: Double = t >= 0.9 ? 1 : (p < 0.15 ? 1 : p < 0.30 ? 0.2 : p < 0.45 ? 1 : p < 0.60 ? 0.35 : 1)
            stroke(Path(roundedRect: CGRect(x: 3, y: 7, width: 18, height: 13), cornerRadius: 2.5), gfx, opacity: opacity)
            var antenna = Path()
            antenna.move(to: CGPoint(x: 8, y: 3)); antenna.addLine(to: CGPoint(x: 12, y: 7)); antenna.addLine(to: CGPoint(x: 16, y: 3))
            let draw = t >= 0.7 ? 1 : easeOut(clamp(t / 0.7))
            stroke(antenna.trimmedPath(from: 0, to: max(draw, 0.001)), gfx)
        case .library:
            var base = Path(); base.move(to: CGPoint(x: 2.5, y: 22)); base.addLine(to: CGPoint(x: 21.5, y: 22))
            stroke(base, gfx)
            // tab-bump: the two upright books settle, 660 ms in.
            let bump = clamp((t - 0.66) / 0.35)
            let dip = bump <= 0 || bump >= 1 ? 0 : (bump < 0.35 ? bump / 0.35 : 1 - (bump - 0.35) / 0.65)
            for x in [3.5, 10.0] {
                var c = gfx
                c.translateBy(x: x + 2.25, y: 4 + dip * 0.8); c.scaleBy(x: 1, y: 1 - dip * 0.03); c.translateBy(x: -(x + 2.25), y: -4)
                stroke(Path(roundedRect: CGRect(x: x, y: 4, width: 4.5, height: 16), cornerRadius: 1), c)
            }
            // tab-jump: the leaning book hops.
            let jump = jumpOffset(t / 1.1)
            var lean = gfx
            lean.translateBy(x: 0, y: -9 * jump)
            lean.translateBy(x: 18.25, y: 12.5); lean.rotate(by: .degrees(-12)); lean.translateBy(x: -18.25, y: -12.5)
            stroke(Path(roundedRect: CGRect(x: 16, y: 5, width: 4.5, height: 15), cornerRadius: 1), lean)
        case .playlists:
            // tab-draw on each line (100 ms apart), tab-pop on the triangle (300 ms in, with overshoot).
            let lines: [(CGPoint, CGPoint)] = [
                (CGPoint(x: 3.5, y: 6), CGPoint(x: 16.5, y: 6)),
                (CGPoint(x: 3.5, y: 11), CGPoint(x: 16.5, y: 11)),
                (CGPoint(x: 3.5, y: 16), CGPoint(x: 9.5, y: 16)),
            ]
            for (index, line) in lines.enumerated() {
                let p = t >= 5 ? 1 : easeOut(clamp((t - Double(index) * 0.1) / 0.5))
                var path = Path(); path.move(to: line.0); path.addLine(to: line.1)
                if p > 0 { stroke(path.trimmedPath(from: 0, to: p), gfx) }
            }
            let pop = t >= 5 ? 1 : easeOutBack(clamp((t - 0.3) / 0.6))
            var tri = Path()
            tri.move(to: CGPoint(x: 14, y: 14.5)); tri.addLine(to: CGPoint(x: 14, y: 20.5)); tri.addLine(to: CGPoint(x: 19.5, y: 17.5)); tri.closeSubpath()
            var c = gfx
            c.translateBy(x: 16.75, y: 17.5); c.scaleBy(x: pop, y: pop); c.translateBy(x: -16.75, y: -17.5)
            if pop > 0.001 { stroke(tri, c) }
        case .settings:
            for y in [7.0, 17.0] {
                var line = Path(); line.move(to: CGPoint(x: 4, y: y)); line.addLine(to: CGPoint(x: 20, y: y))
                stroke(line, gfx)
            }
            // tab-slide-left / right: the knobs cross over and back (1 s, ease in-out).
            let p = clamp(t / 1.0)
            let wave = p >= 1 ? 0 : sin(.pi * min(p / 0.4, 1) / 2) * (p <= 0.4 ? 1 : max(0, 1 - (p - 0.4) / 0.6))
            for (cx, cy, direction) in [(15.0, 7.0, -1.0), (9.0, 17.0, 1.0)] {
                let circle = Path(ellipseIn: CGRect(x: cx - 2.5 + direction * 8 * wave, y: cy - 2.5, width: 5, height: 5))
                gfx.fill(circle, with: .color(knob))
                stroke(circle, gfx)
            }
        }
    }

    private static func clamp(_ x: Double) -> Double { min(max(x, 0), 1) }
    private static func easeOut(_ x: Double) -> Double { 1 - pow(1 - x, 3) }
    private static func easeOutBack(_ x: Double) -> Double {
        let c1 = 1.7, c3 = c1 + 1
        return 1 + c3 * pow(x - 1, 3) + c1 * pow(x - 1, 2)
    }

    /// Linear keyframes (position, translateY, scaleX, scaleY), eased between them.
    private static func keyframes(_ frames: [(Double, Double, Double, Double)], _ p: Double) -> (Double, Double, Double) {
        for index in 1..<frames.count where p <= frames[index].0 {
            let a = frames[index - 1], b = frames[index]
            let u = (p - a.0) / (b.0 - a.0)
            let e = u * u * (3 - 2 * u)
            return (a.1 + (b.1 - a.1) * e, a.2 + (b.2 - a.2) * e, a.3 + (b.3 - a.3) * e)
        }
        return (0, 1, 1)
    }

    /// tab-jump: up to the top at 38 %, back down by 60 %, a small rebound at 70 %, still by 80 %.
    private static func jumpOffset(_ p: Double) -> Double {
        if p <= 0 || p >= 0.8 { return 0 }
        if p < 0.38 { return sin(.pi / 2 * p / 0.38) }
        if p < 0.60 { let u = (p - 0.38) / 0.22; return 1 - u * u }
        if p < 0.70 { return 0.2 * sin(.pi * (p - 0.60) / 0.10) }
        return 0.2 * (1 - (p - 0.70) / 0.10) * 0
    }
}
