import SwiftUI

struct NightsView: View {
    @EnvironmentObject private var store: SleepStore
    @State private var searchText = ""
    @State private var selectedRecord: SleepRecord?
    @State private var showingAdd = false
    @State private var deleteError: String?
    /// Screenshot tooling: pass `-showNightDetail` to open the first night.

    private var filtered: [SleepRecord] {
        let all = store.records
        guard !searchText.isEmpty else { return all }
        let q = searchText.lowercased()
        return all.filter {
            $0.date.contains(q)
                || $0.notes.lowercased().contains(q)
                || $0.source.lowercased().contains(q)
                || DateUtil.display($0.date, format: "MMMM yyyy EEEE").lowercased().contains(q)
        }
    }

    private var monthGroups: [(key: String, records: [SleepRecord])] {
        let grouped = Dictionary(grouping: filtered) { DateUtil.monthKey($0.date) }
        return grouped.keys.sorted(by: >).map { (key: $0, records: grouped[$0] ?? []) }
    }

    var body: some View {
        NavigationStack {
            Group {
                if store.records.isEmpty {
                    emptyBody
                } else {
                    list
                }
            }
            .background(Color.appPage)
            .navigationTitle("Nights")
            .toolbarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showingAdd = true
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("Add a night")
                }
            }
            .sheet(item: $selectedRecord) { record in
                NightDetailView(record: record)
            }
            .sheet(isPresented: $showingAdd) {
                NightFormView(mode: .add)
            }
            .onAppear {
                if ProcessInfo.processInfo.arguments.contains("-showNightDetail"),
                   selectedRecord == nil,
                   let first = store.records.first {
                    selectedRecord = first
                }
            }
            .overlay(alignment: .bottom) {
                if let undo = store.pendingUndo {
                    UndoToast(
                        message: "Night deleted",
                        undo: { Task { await store.undoDelete() } },
                        dismiss: {
                            if store.pendingUndo?.id == undo.id { store.pendingUndo = nil }
                        }
                    )
                    .padding(.bottom, 8)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                } else if let deleteError {
                    UndoToast(
                        message: deleteError,
                        undo: {},
                        dismiss: { self.deleteError = nil }
                    )
                    .padding(.bottom, 8)
                }
            }
            .animation(.spring(duration: 0.3), value: store.pendingUndo)
        }
    }

    private var list: some View {
        List {
            ForEach(monthGroups, id: \.key) { group in
                Section {
                    ForEach(group.records) { record in
                        NightRow(record: record)
                            .contentShape(Rectangle())
                            .onTapGesture { selectedRecord = record }
                            .listRowBackground(Color.appSurface)
                            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                Button(role: .destructive) {
                                    delete(record)
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                    }
                } header: {
                    Text(DateUtil.monthTitle(group.key)).microLabel()
                }
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .searchable(text: $searchText, prompt: "Search dates, notes, sources")
        .refreshable { await store.refresh() }
        .overlay {
            if !searchText.isEmpty && filtered.isEmpty {
                ContentUnavailableView.search(text: searchText)
            }
        }
    }

    private var emptyBody: some View {
        ScrollView {
            VStack(spacing: 14) {
                switch store.loadState {
                case .loading, .idle:
                    ProgressView().padding(.top, 80)
                case .failed(let message):
                    EmptyStateCard(
                        icon: "antenna.radiowaves.left.and.right.slash",
                        title: "Can't reach your server",
                        message: message,
                        actionTitle: "Try again",
                        action: { Task { await store.refresh() } }
                    )
                    .padding(.top, 40)
                case .loaded:
                    EmptyStateCard(
                        icon: "moon.zzz",
                        title: "No nights logged",
                        message: "Add your first night with the + button, or sync your Apple Health history from Settings.",
                        actionTitle: "Add a night",
                        action: { showingAdd = true }
                    )
                    .padding(.top, 40)
                }
            }
            .padding(.horizontal, 16)
        }
        .refreshable { await store.refresh() }
    }

    private func delete(_ record: SleepRecord) {
        Task {
            do {
                try await store.deleteNight(record)
            } catch {
                deleteError = (error as? APIError)?.errorDescription ?? error.localizedDescription
            }
        }
    }
}

// MARK: - Row

struct NightRow: View {
    let record: SleepRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text(DateUtil.display(record.date, format: "EEE d"))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.appInk)
                    .frame(minWidth: 58, alignment: .leading)
                StarRating(quality: record.quality, compact: true)
                if let label = record.sourceLabel {
                    SourceChip(label: label)
                }
                Spacer()
                Text("\(Format.hours(record.hours))h")
                    .font(.system(.subheadline, design: .serif).weight(.semibold))
                    .foregroundStyle(Color.appInk)
            }
            if let stages = record.stages {
                StageMiniBar(stages: stages, height: 4)
            }
            if !record.notes.isEmpty {
                Text(record.notes)
                    .font(.caption)
                    .foregroundStyle(Color.appMuted)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 3)
        .accessibilityElement(children: .combine)
    }
}
