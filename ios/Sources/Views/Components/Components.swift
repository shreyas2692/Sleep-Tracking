import SwiftUI

// MARK: - Stars

struct StarRating: View {
    let quality: Int
    var compact = false

    var body: some View {
        HStack(spacing: compact ? 1 : 2) {
            ForEach(1...5, id: \.self) { i in
                Image(systemName: i <= quality ? "star.fill" : "star")
                    .font(compact ? .caption2 : .caption)
                    .foregroundStyle(i <= quality ? Color.appAccent : Color.appBaseline)
            }
        }
        .accessibilityLabel("Quality \(quality) of 5")
    }
}

// MARK: - Source chip ("Watch" / "Fitbit" for imported nights)

struct SourceChip: View {
    let label: String

    var body: some View {
        Text(label)
            .font(.caption2.weight(.medium))
            .foregroundStyle(Color.appInk2)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Capsule().fill(Color.appInset))
            .overlay(Capsule().strokeBorder(Color.appBorder, lineWidth: 1))
    }
}

// MARK: - Stage mini-bar (proportional composition strip)

struct StageMiniBar: View {
    let stages: SleepStages
    var height: CGFloat = 5

    var body: some View {
        GeometryReader { geo in
            let total = max(stages.totalMinutes, 1)
            HStack(spacing: 1.5) {
                segment(minutes: stages.deep, total: total, width: geo.size.width, color: .stageDeep)
                segment(minutes: stages.rem, total: total, width: geo.size.width, color: .stageRem)
                segment(minutes: stages.light, total: total, width: geo.size.width, color: .stageLight)
                segment(minutes: stages.awake, total: total, width: geo.size.width, color: .stageAwake)
            }
        }
        .frame(height: height)
        .clipShape(Capsule())
        .accessibilityLabel("Stages: \(Format.minutes(stages.deep)) deep, \(Format.minutes(stages.rem)) REM, \(Format.minutes(stages.light)) light, \(Format.minutes(stages.awake)) awake")
    }

    @ViewBuilder
    private func segment(minutes: Int, total: Int, width: CGFloat, color: Color) -> some View {
        if minutes > 0 {
            Rectangle()
                .fill(color)
                .frame(width: max(2, width * CGFloat(minutes) / CGFloat(total) - 1.5))
        }
    }
}

// MARK: - Stage legend row

struct StageLegend: View {
    var body: some View {
        HStack(spacing: 14) {
            legendItem("Deep", .stageDeep)
            legendItem("REM", .stageRem)
            legendItem("Light", .stageLight)
            legendItem("Awake", .stageAwake)
        }
    }

    private func legendItem(_ name: String, _ color: Color) -> some View {
        HStack(spacing: 5) {
            RoundedRectangle(cornerRadius: 2)
                .fill(color)
                .frame(width: 9, height: 9)
            Text(name)
                .font(.caption2)
                .foregroundStyle(Color.appInk2)
        }
    }
}

// MARK: - Empty / error states

struct EmptyStateCard: View {
    let icon: String
    let title: String
    let message: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 30, weight: .light))
                .foregroundStyle(Color.appMuted)
            Text(title)
                .serifDisplay(.title3)
                .multilineTextAlignment(.center)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color.appInk2)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.bordered)
                    .padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 24)
        .card()
    }
}

// MARK: - Undo toast (no alert dialogs)

struct UndoToast: View {
    let message: String
    let undo: () -> Void
    let dismiss: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color.appInk)
                .lineLimit(2)
            Spacer(minLength: 8)
            Button("Undo") {
                undo()
            }
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Color.appAccentPressed)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.appSurface)
                .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.appBorder, lineWidth: 1)
        )
        .padding(.horizontal, 16)
        .task {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            dismiss()
        }
    }
}

// MARK: - Wordmark

struct Wordmark: View {
    var body: some View {
        Text("Sleep Tracker")
            .font(.system(.headline, design: .serif).weight(.medium))
            .foregroundStyle(Color.appInk)
    }
}
