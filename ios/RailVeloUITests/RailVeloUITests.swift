import XCTest
import UIKit

/// Exercises the shipped replay adapter, matcher, SQLite store and share controller.
/// No live location permission, account, network or substitute ViewModel is used.
final class RailVeloUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testReplayRecordingGraphHistoryCSVAndDeletion() throws {
        let app = XCUIApplication()
        app.launch()
        defer { app.terminate() }

        let start = app.buttons["ride.start"]
        waitUntil("The real network and history store finish initialization") { start.exists && start.isEnabled }
        let mode = app.segmentedControls["ride.mode"]
        XCTAssertTrue(mode.waitForExistence(timeout: 10))
        mode.buttons["リプレイ（テスト）"].tap()
        XCTAssertTrue(start.isHittable)
        start.tap()
        let pause = app.buttons["ride.pause"]
        waitUntil("Replay is recording") { pause.exists && pause.isEnabled }
        let speed = element("ride.speed", in: app)
        waitUntil("Valid GPS speed reaches the speedometer") {
            (speed.value as? String)?.contains("時速") == true
        }
        XCTAssertEqual(speed.label, "現在速度")
        attach("01-replay-started")

        let chart = element("ride.chart", in: app)
        reveal(chart, in: app.scrollViews["ride.scroll"], app: app)
        let ranges = app.segmentedControls["ride.chart.range"]
        for (label, name) in [("60秒", "02-chart-60-seconds"), ("5分", "03-chart-five-minutes"), ("全体", "04-chart-entire-session")] {
            let button = ranges.buttons[label]
            XCTAssertTrue(button.isHittable)
            button.tap()
            waitUntil("\(label) graph contains recorded observations") {
                guard let value = chart.value as? String else { return false }
                return value.contains(label) && value.range(of: #"有効な速度 [1-9][0-9]* 件"#, options: .regularExpression) != nil
            }
            XCTAssertTrue(button.isSelected)
            try assertGraphMarksRendered(chart, app: app)
            attach(name)
        }

        XCTAssertTrue(pause.isHittable)
        pause.tap()
        let resume = app.buttons["ride.resume"]
        waitUntil("Pause is durably stored before resuming") { resume.exists && resume.isEnabled }
        XCTAssertTrue(resume.isHittable)
        attach("05-paused")
        app.buttons["ride.history"].tap()
        let pausedRow = newestHistoryRow(in: app)
        waitUntil("The current paused replay appears in history") {
            (pausedRow.value as? String)?.contains("一時停止中") == true
        }
        pausedRow.swipeLeft()
        XCTAssertFalse(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "history.delete.")).firstMatch.exists)
        attach("06-active-history-cannot-delete")
        app.buttons["history.close"].tap()
        XCTAssertTrue(resume.isHittable)
        resume.tap()
        waitUntil("Replay resumes") { pause.exists && pause.isEnabled }
        attach("07-resumed")

        app.buttons["ride.finish"].tap()
        let confirmFinish = app.buttons["記録を終了"]
        XCTAssertTrue(confirmFinish.waitForExistence(timeout: 10))
        confirmFinish.tap()
        waitUntil("Session finish is durably stored") { start.exists && start.isEnabled }
        attach("08-finished")
        app.buttons["ride.history"].tap()
        let row = newestHistoryRow(in: app)
        waitUntil("The completed synthetic replay appears in history") {
            (row.value as? String)?.contains("リプレイのテスト記録、記録終了") == true
        }
        let createdRowID = row.identifier
        XCTAssertTrue(createdRowID.hasPrefix("history.row."))
        row.tap()
        let share = app.buttons["history.shareCSV"]
        XCTAssertTrue(share.waitForExistence(timeout: 20))
        reveal(share, in: app.scrollViews["history.detail.scroll"], app: app)
        waitUntil("The persisted CSV is ready to share") { share.exists && share.isHittable }
        let historyChart = element("history.chart", in: app)
        XCTAssertTrue(historyChart.exists)
        attach("09-persisted-history")
        share.tap()
        let activityView = app.otherElements["ActivityListView"]
        let close = app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "Close", "閉じる")).firstMatch
        waitUntil("A native CSV share sheet opens") {
            activityView.exists || app.collectionViews.firstMatch.exists && close.exists && close.isHittable
        }
        attach("10-native-csv-share-sheet")
        if close.exists && close.isHittable {
            close.tap()
        } else {
            activityView.swipeDown()
        }
        waitUntil("The share sheet is dismissed without sending the file") { share.isHittable }
        app.navigationBars["走行の詳細"].buttons.element(boundBy: 0).tap()
        let completedRow = app.buttons[createdRowID]
        XCTAssertTrue(completedRow.waitForExistence(timeout: 10))
        completedRow.swipeLeft()
        let delete = app.buttons[createdRowID.replacingOccurrences(of: "history.row.", with: "history.delete.")]
        if delete.exists && delete.isHittable { delete.tap() }
        let confirmDelete = app.buttons["位置情報と走行履歴を削除"]
        XCTAssertTrue(confirmDelete.waitForExistence(timeout: 10))
        attach("11-delete-confirmation")
        confirmDelete.tap()
        waitUntil("Only this test's completed replay is deleted") { !completedRow.exists }
        attach("12-history-deleted")
        app.buttons["history.close"].tap()
        XCTAssertTrue(start.isHittable)
    }

    @MainActor
    func testLargeTextAccessibility() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--replay-smoke", "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityL"]
        app.launch()
        defer { app.terminate() }
        let pause = app.buttons["ride.pause"]
        waitUntil("The replay is available with accessibility text sizes") { pause.exists && pause.isEnabled }
        pause.tap()
        let resume = app.buttons["ride.resume"]
        waitUntil("The large-text recording controls stay usable") { resume.exists && resume.isEnabled }
        XCTAssertTrue(resume.isHittable)
        XCTAssertFalse(resume.label.isEmpty)
        attach("13-large-text-main")
        if #available(iOS 17.0, *) {
            try app.performAccessibilityAudit(for: [.hitRegion, .sufficientElementDescription, .textClipped, .dynamicType])
        }
        let chart = element("ride.chart", in: app)
        reveal(chart, in: app.scrollViews["ride.scroll"], app: app)
        XCTAssertTrue(app.segmentedControls["ride.chart.range"].buttons["全体"].isHittable)
        attach("14-large-text-scroll-and-chart")
    }

    /// The workflow sets the actual Simulator appearance to dark before this test.
    @MainActor
    func testDarkReplayAccessibility() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--replay-smoke"]
        app.launch()
        defer { app.terminate() }
        let pause = app.buttons["ride.pause"]
        waitUntil("The replay is recording in dark appearance") { pause.exists && pause.isEnabled }
        let speed = element("ride.speed", in: app)
        waitUntil("The dark-mode speedometer contains real replay speed") { (speed.value as? String)?.contains("時速") == true }
        XCTAssertTrue(pause.isHittable)
        pause.tap()
        waitUntil("Dark-mode controls remain usable") { app.buttons["ride.resume"].exists && app.buttons["ride.resume"].isEnabled }
        attach("15-dark-replay-main")
        if #available(iOS 17.0, *) {
            try app.performAccessibilityAudit(for: [.hitRegion, .sufficientElementDescription, .textClipped])
        }
        let chart = element("ride.chart", in: app)
        reveal(chart, in: app.scrollViews["ride.scroll"], app: app)
        attach("16-dark-replay-chart")
    }

    @MainActor private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    @MainActor private func newestHistoryRow(in app: XCUIApplication) -> XCUIElement {
        let row = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "history.row.")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        return row
    }

    @MainActor private func reveal(_ element: XCUIElement, in scroll: XCUIElement, app: XCUIApplication) {
        for _ in 0..<8 {
            if element.exists && element.isHittable && element.frame.maxY < app.frame.maxY - 125 { return }
            scroll.swipeUp()
        }
        XCTAssertTrue(element.exists && element.isHittable, "The real scroll view must reveal the requested control")
    }

    @MainActor private func waitUntil(_ description: String, timeout: TimeInterval = 30, _ predicate: @escaping () -> Bool) {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in predicate() }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: timeout), .completed, description)
    }

    @MainActor private func attach(_ name: String) {
        XCTContext.runActivity(named: name) { activity in
            let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            screenshot.name = name
            screenshot.lifetime = .keepAlways
            activity.add(screenshot)
        }
    }

    /// Pixel evidence supplements the accessibility tree: the cyan data marks must
    /// actually be drawn inside the chart, beyond simply finding its container.
    @MainActor private func assertGraphMarksRendered(_ chart: XCUIElement, app: XCUIApplication) throws {
        let image = try XCTUnwrap(XCUIScreen.main.screenshot().image.cgImage)
        let scaleX = CGFloat(image.width) / app.frame.width
        let scaleY = CGFloat(image.height) / app.frame.height
        let frame = chart.frame
        let region = CGRect(x: frame.minX * scaleX, y: frame.minY * scaleY, width: frame.width * scaleX, height: frame.height * scaleY)
        let cropped = try XCTUnwrap(image.cropping(to: region))
        let width = cropped.width, height = cropped.height
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        let cyanPixels: Int = try pixels.withUnsafeMutableBytes { bytes in
            let context = try XCTUnwrap(CGContext(data: bytes.baseAddress, width: width, height: height,
                bitsPerComponent: 8, bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue))
            context.draw(cropped, in: CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
            var count = 0
            for index in stride(from: 0, to: bytes.count, by: 4) {
                if bytes[index] < 100 && bytes[index + 1] > 110 && bytes[index + 2] > 130 { count += 1 }
            }
            return count
        }
        XCTAssertGreaterThan(cyanPixels, 12, "Recorded speed marks must be visible in the rendered chart")
    }
}
