import SwiftUI

/// Add or edit a manual night. The server owns validation (no future dates,
/// quality 1-5, notes <= 500 chars); we mirror the easy parts client-side.
struct NightFormView: View {
    enum Mode {
        case add
        case edit(SleepRecord)
    }

    @EnvironmentObject private var store: SleepStore
    @Environment(\.dismiss) private var dismiss

    let mode: Mode

    @State private var date: Date
    @State private var bedtime: Date
    @State private var wake: Date
    @State private var quality: Double
    @State private var notes: String
    @State private var isSaving = false
    @State private var errorMessage: String?

    private static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f
    }()

    init(mode: Mode) {
        self.mode = mode
        switch mode {
        case .add:
            _date = State(initialValue: Date())
            _bedtime = State(initialValue: Self.time(hour: 23, minute: 0))
            _wake = State(initialValue: Self.time(hour: 7, minute: 0))
            _quality = State(initialValue: 3)
            _notes = State(initialValue: "")
        case .edit(let record):
            _date = State(initialValue: DateUtil.date(from: record.date) ?? Date())
            _bedtime = State(initialValue: Self.timeFormatter.date(from: record.bedtime) ?? Self.time(hour: 23, minute: 0))
            _wake = State(initialValue: Self.timeFormatter.date(from: record.wake) ?? Self.time(hour: 7, minute: 0))
            _quality = State(initialValue: Double(record.quality))
            _notes = State(initialValue: record.notes)
        }
    }

    private static func time(hour: Int, minute: Int) -> Date {
        Calendar.current.date(bySettingHour: hour, minute: minute, second: 0, of: Date()) ?? Date()
    }

    private var isEdit: Bool {
        if case .edit = mode { return true }
        return false
    }

    private var previewHours: Double {
        let bed = Self.timeFormatter.string(from: bedtime)
        let wk = Self.timeFormatter.string(from: wake)
        guard let b = Self.timeFormatter.date(from: bed), let w = Self.timeFormatter.date(from: wk) else { return 0 }
        var interval = w.timeIntervalSince(b) / 3600.0
        if interval <= 0 { interval += 24 } // overnight wraparound: 23:00 -> 07:00 = 8h
        return interval
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Night") {
                    DatePicker("Date", selection: $date, in: ...Date(), displayedComponents: .date)
                    DatePicker("Bedtime", selection: $bedtime, displayedComponents: .hourAndMinute)
                    DatePicker("Wake", selection: $wake, displayedComponents: .hourAndMinute)
                    HStack {
                        Text("Duration")
                            .foregroundStyle(Color.appInk2)
                        Spacer()
                        Text("\(Format.hours(previewHours))h")
                            .font(.system(.body, design: .serif).weight(.medium))
                            .foregroundStyle(Color.appInk)
                    }
                }
                .listRowBackground(Color.appSurface)

                Section("Quality") {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            StarRating(quality: Int(quality))
                            Spacer()
                            Text("\(Int(quality)) of 5")
                                .font(.caption)
                                .foregroundStyle(Color.appMuted)
                        }
                        Slider(value: $quality, in: 1...5, step: 1) {
                            Text("Quality")
                        }
                    }
                }
                .listRowBackground(Color.appSurface)

                Section("Notes") {
                    TextField("Anything worth remembering?", text: $notes, axis: .vertical)
                        .lineLimit(2...5)
                        .onChange(of: notes) { _, newValue in
                            if newValue.count > 500 { notes = String(newValue.prefix(500)) }
                        }
                }
                .listRowBackground(Color.appSurface)

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .font(.subheadline)
                            .foregroundStyle(Color.appInk2)
                    }
                    .listRowBackground(Color.appInset)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.appPage)
            .navigationTitle(isEdit ? "Edit Night" : "Add Night")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .disabled(isSaving)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        save()
                    } label: {
                        if isSaving {
                            ProgressView()
                        } else {
                            Text("Save").fontWeight(.semibold)
                        }
                    }
                    .disabled(isSaving)
                }
            }
        }
        .presentationDetents([.large])
        .interactiveDismissDisabled(isSaving)
    }

    private func save() {
        errorMessage = nil
        isSaving = true
        let fields = APIClient.NightFields(
            date: DateUtil.string(from: date),
            bedtime: Self.timeFormatter.string(from: bedtime),
            wake: Self.timeFormatter.string(from: wake),
            quality: Int(quality),
            notes: notes.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        Task {
            do {
                switch mode {
                case .add:
                    try await store.addNight(fields)
                case .edit(let record):
                    try await store.editNight(id: record.id, fields: fields)
                }
                dismiss()
            } catch {
                errorMessage = (error as? APIError)?.errorDescription ?? error.localizedDescription
                isSaving = false
            }
        }
    }
}
