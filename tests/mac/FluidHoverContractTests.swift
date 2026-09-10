import Foundation

@main
struct FluidHoverContractTests {
    static func main() {
        func target(_ id: String, _ group: String, _ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> FluidHoverTarget {
            FluidHoverTarget(id: id, group: group, rect: CGRect(x: x, y: y, width: w, height: h))
        }
        let sessions = [target("a", "unfiled", 0, 0, 220, 36), target("b", "unfiled", 0, 40, 220, 36),
                        target("c", "folder", 12, 112, 208, 36), target("d", "folder", 12, 152, 208, 36)]
        func pick(_ x: CGFloat, _ y: CGFloat, _ items: [FluidHoverTarget] = sessions) -> String? {
            FluidHoverPicking.nearest(CGPoint(x: x, y: y), targets: items, maxGap: 12)?.id
        }
        precondition(pick(100, 20) == "a")
        precondition(pick(100, 37) == "a" && pick(100, 39) == "b", "small row gaps retain visual continuity")
        precondition(pick(100, 94) == nil, "folder heading must not highlight a session in either group")
        precondition(pick(2, 130) == nil, "folder indentation is outside its hover group")
        precondition(pick(100, 200) == nil && pick(-1, 20) == nil, "outside group cannot attract hover")
        precondition(pick(100, 20, []) == nil)
        precondition(pick(100, 20, [target("zero", "cards", 0, 0, 0, 0)]) == nil)
        precondition(pick(100, 38) == pick(100, 38, Array(sessions.reversed())), "ties stay deterministic after preference ordering changes")
        precondition(pick(100, 20, [target("b", "unfiled", 0, 0, 220, 36)]) == "b", "refresh uses current IDs, not old indices")
        print("PASS: row gaps, folder boundary/indentation, outside groups, empty/invalid targets, stable ties and refreshed identities")
    }
}
