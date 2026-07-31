import SwiftUI

struct NightDetailView: View {
    @EnvironmentObject private var store: SleepStore
    @Environment(\.dismiss) private var dismiss
    let record: SleepRecord
    @State private var showingEdit = false

    /// The list can refresh underneath us; prefer the live copy.
    private var current: SleepRecord {
        store.records.first { $0.id == record.id } ?? record
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header
                    if let stages = current.stages {
                        stageCard(stages)
                    }
                    detailsCard
                    if !current.notes.isEmpty {
                        notesCard
                    }
                }
                .padding(16)
            }
            .background(Color.appPage)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Edit") { showingEdit = true }
                }
            }
            .sheet(isPresented: $showingEdit) {
                NightFormView(mode: .edit(current))
            }
        }
        .presentationDetents([.large, .medium])
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(DateUtil.display(current.date, format: "EEEE MMMM d yyyy"))
                .serifDisplay(.title2)
            HStack(spacing: 10) {
                Text("\(Format.hours(current.hours)) hours")
                    .font(.subheadline)
                    .foregroundStyle(Color.appInk2)
                StarRating(quality: current.quality)
                if let label = current.sourceLabel {
                    SourceChip(label: label)
                }
            }
        }
    }

    private func stageCard(_ stages: SleepStages) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Stages").microLabel()
            StageMiniBar(stages: stages, height: 10)
            VStack(spacing: 8) {
                stageRow("Deep", stages.deep, total: stages.totalMinutes, color: .stageDeep)
                stageRow("REM", stages.rem, total: stages.totalMinutes, color: .stageRem)
                stageRow("Light", stages.light, total: stages.totalMinutes, color: .stageLight)
                stageRow("Awake", stages.awake, total: stages.totalMinutes, color: .stageAwake)
            }
            if let efficiency = current.efficiency {
                Divider().overlay(Color.appBorder)
                HStack {
                    Text("Efficiency")
                        .font(.subheadline)
                        .foregroundStyle(Color.appInk2)
                    Spacer()
                    Text("\(Int(efficiency.rounded()))%")
                        .font(.system(.subheadline, design: .serif).weight(.semibold))
                        .foregroundStyle(Color.appInk)
                }
            }
        }
        .card()
    }

    private func stageRow(_ name: String, _ minutes: Int, total: Int, color: Color) -> some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 2)
                .fill(color)
                .frame(width: 10, height: 10)
            Text(name)
                .font(.subheadline)
                .foregroundStyle(Color.appInk2)
            Spacer()
            if total > 0 {
                Text("\(Int((Double(minutes) / Double(total) * 100).rounded()))%")
                    .font(.caption)
                    .foregroundStyle(Color.appMuted)
            }
            Text(Format.minutes(minutes))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color.appInk)
                .frame(minWidth: 52, alignment: .trailing)
        }
    }

    private var detailsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Night").microLabel()
            detailRow("Bedtime", current.bedtime)
            detailRow("Wake", current.wake)
            detailRow("Duration", "\(Format.hours(current.hours))h")
            detailRow("Source", current.sourceLabel ?? "Manual entry")
        }
        .card()
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .font(.subheadline)
                .foregroundStyle(Color.appInk2)
            Spacer()
            Text(value)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color.appInk)
        }
    }

    private var notesCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Notes").microLabel()
            Text(current.notes)
                .font(.subheadline)
                .foregroundStyle(Color.appInk)
        }
        .card()
    }
}
