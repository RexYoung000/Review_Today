import SwiftData
import SwiftUI

struct TodayActivityHeatmap: View {
    let cache: TodayActivityCache
    var onOpenLearning: (UUID?) -> Void
    var onOpenKnowledge: (UUID) -> Void
    @Environment(\.runway) private var runway
    @Environment(\.calendar) private var calendar
    @Environment(\.timeZone) private var timeZone
    @Environment(\.locale) private var locale
    @State private var selectedDate: Date?
    @State private var day = Date.now
    @State private var compact = false

    var body: some View {
        var calendar = calendar
        calendar.timeZone = timeZone
        let snapshot = cache.snapshot(activities: cache.sourceActivities,
            calendar: calendar, now: day, locale: locale)
        return card(snapshot)
            .onAppear(perform: updateDay)
            .onChange(of: timeZone) { _, _ in updateDay() }
            .onChange(of: calendar) { _, _ in updateDay() }
            .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in updateDay() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in updateDay() }
    }

    private func updateDay() {
        var current = calendar; current.timeZone = timeZone
        let next = Date.now
        if current.startOfDay(for: day) != current.startOfDay(for: next) { day = next }
    }

    private func card(_ snapshot: TodayActivitySnapshot) -> some View {
        RunwayCard(padding: snapshot.isEmpty ? 12 : Runway.gap) {
            VStack(alignment: .leading, spacing: snapshot.isEmpty ? 10 : 16) {
                HStack(spacing: 44) {
                    stat(snapshot.activeDays, "活跃天数")
                    stat(snapshot.currentStreak, "当前连续天数")
                    stat(snapshot.longestStreak, "最长连续天数")
                    Spacer()
                    Text("最近 26 周").font(.caption).foregroundStyle(.secondary)
                }
                // The measured width chooses a size before building cells. One
                // grid replaces three independently evaluated ViewThatFits trees.
                GeometryReader { geometry in
                    let large = geometry.size.width >= 20 + 26 * 16 + 25 * 5
                    let cell: CGFloat = large ? 16 : 12
                    let spacing: CGFloat = large ? 5 : 4
                    ScrollView(.horizontal) { grid(snapshot, cell: cell, spacing: spacing) }
                        .scrollDisabled(geometry.size.width >= 20 + 26 * cell + 25 * spacing)
                }
                .onGeometryChange(for: Bool.self) { $0.size.width < 561 } action: { value in if compact != value { compact = value } }
                .frame(height: compact ? 128 : 162)
                HStack(spacing: 5) {
                    Text("较少")
                    ForEach(0..<5, id: \.self) { level in
                        RoundedRectangle(cornerRadius: 3).fill(color(level)).frame(width: 14, height: 14)
                    }
                    Text("较多")
                }.font(.caption2).foregroundStyle(.secondary)
                if let selectedDate {
                    Divider()
                    details(selectedDate, rows: snapshot.activitiesByDay[selectedDate] ?? [])
                }
            }
        }
    }

    private func stat(_ value: Int, _ title: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(value) 天").font(.title2.bold()).foregroundStyle(runway.ink)
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
    }

    private func grid(_ snapshot: TodayActivitySnapshot, cell: CGFloat, spacing: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: spacing) {
                ForEach(0..<26, id: \.self) { week in
                    Color.clear.frame(width: cell, height: 14).overlay(alignment: .leading) {
                        if let month = snapshot.months[week] {
                            Text(month).font(.caption2).foregroundStyle(.secondary).fixedSize().accessibilityHidden(true)
                        }
                    }
                }
            }.padding(.leading, 20)
            HStack(alignment: .top, spacing: 8) {
                VStack(spacing: spacing) {
                    ForEach(Array(snapshot.weekdayLabels.enumerated()), id: \.offset) { _, label in
                        Text(label).frame(width: 12, height: cell)
                    }
                }.font(.caption2).foregroundStyle(.secondary)
                ActivityDayGrid(days: snapshot.days, size: cell, spacing: spacing,
                    colors: (0..<5).map { NSColor(color($0)) }, border: NSColor(runway.hairline)) { selectedDate = $0 }
                    .frame(width: 26 * cell + 25 * spacing, height: 7 * cell + 6 * spacing)
            }
        }
    }

    private func details(_ date: Date, rows: [TodayActivity]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(date, format: .dateTime.year().month().day()).font(.subheadline.weight(.semibold))
                Text("\(rows.count) 次有效活动").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(rows) { item in
                Button {
                    if let id = item.sessionID { onOpenLearning(id) }
                    else if let id = item.knowledgeID { onOpenKnowledge(id) }
                } label: {
                    HStack {
                        Text(TodayActivity.kindLabel(item.kind)).font(.caption).foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
                        Text(item.title).foregroundStyle(runway.ink).lineLimit(1)
                        Spacer()
                        Text(item.date, style: .time).font(.caption).foregroundStyle(.secondary)
                        Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.secondary)
                    }.contentShape(Rectangle())
                }.buttonStyle(InteractionButtonStyle(padding: 4))
            }
        }
    }

    private func color(_ level: Int) -> Color {
        switch level {
        case 0: runway.field.opacity(0.72)
        case 1: runway.history.opacity(0.22)
        case 2: runway.history.opacity(0.42)
        case 3: runway.history.opacity(0.68)
        default: runway.history
        }
    }
}
