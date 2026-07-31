import SwiftUI
import UIKit

// MARK: - Claude design language tokens, ported from static/style.css.
// Light: warm ivory page, white cards, hairline borders. Dark: warm charcoal.
// Accent terracotta. Chart + stage ramp values are the dataviz-validated set
// documented in the CSS header (light/dark variants per mode).

private extension UIColor {
    convenience init(hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255.0,
            green: CGFloat((hex >> 8) & 0xFF) / 255.0,
            blue: CGFloat(hex & 0xFF) / 255.0,
            alpha: 1.0
        )
    }

    static func dynamic(light: UInt32, dark: UInt32) -> UIColor {
        UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light)
        }
    }
}

extension Color {
    // Surfaces
    static let appPage = Color(UIColor.dynamic(light: 0xFAF9F5, dark: 0x262624))
    static let appSurface = Color(UIColor.dynamic(light: 0xFFFFFF, dark: 0x30302E))
    static let appInset = Color(UIColor.dynamic(light: 0xF0EEE6, dark: 0x262624))
    static let appField = Color(UIColor.dynamic(light: 0xF5F4EF, dark: 0x262624))
    // Ink
    static let appInk = Color(UIColor.dynamic(light: 0x141413, dark: 0xF5F4EF))
    static let appInk2 = Color(UIColor.dynamic(light: 0x5E5D59, dark: 0xA8A69E))
    static let appMuted = Color(UIColor.dynamic(light: 0x706E67, dark: 0xA09E95))
    // Lines
    static let appBorder = Color(UIColor.dynamic(light: 0xE8E6DC, dark: 0x3E3E3A))
    static let appGrid = Color(UIColor.dynamic(light: 0xE8E6DC, dark: 0x3E3E3A))
    static let appBaseline = Color(UIColor.dynamic(light: 0xD9D6C8, dark: 0x4C4B45))
    // Accent
    static let appAccent = Color(UIColor.dynamic(light: 0xD97757, dark: 0xD97757))
    static let appAccentPressed = Color(UIColor.dynamic(light: 0xC4633F, dark: 0xE08B6D))
    static let appAccentSoft = Color(UIColor.dynamic(light: 0xF7E8E2, dark: 0x3E312C))
    // Charts
    static let chartBar = Color(UIColor.dynamic(light: 0xD97757, dark: 0xD5714F))
    static let chartBarStrong = Color(UIColor.dynamic(light: 0xC4633F, dark: 0xC4633F))
    // Stage ramp: one terracotta hue, deep darkest -> awake lightest.
    static let stageDeep = Color(UIColor.dynamic(light: 0x8A3A20, dark: 0x9C4526))
    static let stageRem = Color(UIColor.dynamic(light: 0xC4633F, dark: 0xC4633F))
    static let stageLight = Color(UIColor.dynamic(light: 0xDE855E, dark: 0xDE855E))
    static let stageAwake = Color(UIColor.dynamic(light: 0xEDA787, dark: 0xF0B394))
    // Semantics (used sparingly; sleep debt stays neutral per PRODUCT.md)
    static let appGood = Color(UIColor.dynamic(light: 0x4C7A43, dark: 0x86A97C))
}

// MARK: - Card chrome: hairline borders over shadows, 14-16pt radii.

struct CardBackground: ViewModifier {
    var padding: CGFloat = 16

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Color.appSurface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(Color.appBorder, lineWidth: 1)
            )
    }
}

extension View {
    func card(padding: CGFloat = 16) -> some View {
        modifier(CardBackground(padding: padding))
    }

    /// Uppercase tracked micro-label for stat captions.
    func microLabel() -> some View {
        self
            .font(.caption2.weight(.semibold))
            .textCase(.uppercase)
            .kerning(1.1)
            .foregroundStyle(Color.appInk2)
    }
}

/// Serif display style for large stat numbers and screen titles.
struct SerifDisplay: ViewModifier {
    var size: Font.TextStyle = .title

    func body(content: Content) -> some View {
        content
            .font(.system(size, design: .serif).weight(.medium))
            .foregroundStyle(Color.appInk)
    }
}

extension View {
    func serifDisplay(_ size: Font.TextStyle = .title) -> some View {
        modifier(SerifDisplay(size: size))
    }
}

enum Haptics {
    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }

    static func tap() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }
}
