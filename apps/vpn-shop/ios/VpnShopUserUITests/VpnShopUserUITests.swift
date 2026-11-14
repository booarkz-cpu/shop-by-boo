import XCTest

/// UI tests of the customer app in the demo mode of the debug build (fixed data, no network).
final class VpnShopUserUITests: XCTestCase {
    @MainActor
    private func launch(_ tab: String = "vpn") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-CorgiDemo", "-CorgiTab", tab, "-shop_lang", "ru"]
        app.launch()
        return app
    }

    override func setUp() { continueAfterFailure = false }

    @MainActor
    func testVpnScreenShowsConnectAndPlan() {
        let app = launch()
        XCTAssertTrue(app.staticTexts["Подключить"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Премиум · 12 месяцев"].exists)
    }

    @MainActor
    func testConnectTogglesTheStatus() {
        let app = launch()
        XCTAssertTrue(app.staticTexts["VPN отключён"].waitForExistence(timeout: 10))
        app.buttons.matching(NSPredicate(format: "label CONTAINS 'Подключить'")).firstMatch.tap()
        XCTAssertTrue(app.staticTexts["VPN подключён"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testPremiumShowsPlans() {
        let app = launch("premium")
        XCTAssertTrue(app.staticTexts["12 месяцев"].waitForExistence(timeout: 10))
    }

    @MainActor
    func testGiveaways() {
        let app = launch("giveaways")
        XCTAssertTrue(app.staticTexts["Новогоднее колесо"].waitForExistence(timeout: 10))
    }
}
