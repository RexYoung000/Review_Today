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
    @State private var cardWidth: CGFloat = 0

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
        let wide = cardWidth >= 920
        let contentWidth = max(0, cardWidth - 40)
        return RunwayCard(padding: 20) {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text("学习足迹").font(.headline).foregroundStyle(runway.ink)
                    Spacer(minLength: 8)
                    Text("最近 26 周").font(.caption).foregroundStyle(.secondary)
                }
                if wide {
                    HStack(alignment: .top, spacing: 18) {
                        calendarPanel(snapshot, width: contentWidth - 178)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        statistics(snapshot, vertical: true).frame(width: 160)
                    }
                } else {
                    calendarPanel(snapshot, width: contentWidth)
                    statistics(snapshot, vertical: false)
                }
                if let selectedDate {
                    Divider()
                    details(selectedDate, rows: snapshot.activitiesByDay[selectedDate] ?? [])
                }
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width in
            if abs(cardWidth - width) > 1 { cardWidth = width }
        }
    }

    private func calendarPanel(_ snapshot: TodayActivitySnapshot, width: CGFloat) -> some View {
        let spacing: CGFloat = width >= 650 ? 5.5 : 4
        let cell = min(width >= 650 ? 22.0 : 20.0,
                       max(12.0, floor((width - 28 - 25 * spacing) / 26)))
        let gridWidth = 28 + 26 * cell + 25 * spacing
        return VStack(alignment: .leading, spacing: 12) {
            ScrollView(.horizontal) { grid(snapshot, cell: cell, spacing: spacing) }
                .scrollDisabled(width >= gridWidth)
                .frame(height: 22 + 7 * cell + 6 * spacing)
            HStack(spacing: 5) {
                Text("较少")
                ForEach(0..<5, id: \.self) { level in
                    RoundedRectangle(cornerRadius: 3).fill(color(level)).frame(width: 14, height: 14)
                }
                Text("较多")
            }.font(.caption2).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    private func statistics(_ snapshot: TodayActivitySnapshot, vertical: Bool) -> some View {
        let values = [(snapshot.activeDays, "活跃天数"), (snapshot.currentStreak, "当前连续天数"),
                      (snapshot.longestStreak, "最长连续天数")]
        return Group {
            if vertical {
                VStack(spacing: 8) {
                    ForEach(values.indices, id: \.self) { index in stat(values[index].0, values[index].1) }
                }
            } else {
                HStack(spacing: 8) {
                    ForEach(values.indices, id: \.self) { index in stat(values[index].0, values[index].1) }
                }
            }
        }
    }

    private func stat(_ value: Int, _ title: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text("\(value)").font(.system(size: 25, weight: .semibold)).monospacedDigit()
                Text("天").font(.caption).foregroundStyle(.secondary)
            }.foregroundStyle(runway.ink)
            Text(title).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }.frame(maxWidth: .infinity, minHeight: 70, alignment: .leading)
            .padding(.horizontal, 15).padding(.vertical, 8)
            .background(runway.field.opacity(0.65), in: RoundedRectangle(cornerRadius: Runway.chipRadius, style: .continuous))
            .accessibilityElement(children: .combine)
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
