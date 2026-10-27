import XCTest

/// UI tests of the customer app in the demo mode of the debug build (fixed data, no network).
final class VpnShopUserUITests: XCTestCase {
    private func launch(_ tab: String = "vpn") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-CorgiDemo", "-CorgiTab", tab, "-shop_lang", "ru"]
        app.launch()
        return app
    }

    override func setUp() { continueAfterFailure = false }

    func testVpnScreenShowsConnectAndPlan() {
        let app = launch()
        XCTAssertTrue(app.staticTexts["Подключить"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Премиум · 12 месяцев"].exists)
    }

    func testConnectTogglesTheStatus() {
        let app = launch()
        XCTAssertTrue(app.staticTexts["VPN отключён"].waitForExistence(timeout: 10))
        app.buttons.matching(NSPredicate(format: "label CONTAINS 'Подключить'")).firstMatch.tap()
        XCTAssertTrue(app.staticTexts["VPN подключён"].waitForExistence(timeout: 5))
    }

    func testPremiumShowsPlans() {
        let app = launch("premium")
        XCTAssertTrue(app.staticTexts["12 месяцев"].waitForExistence(timeout: 10))
    }

    func testGiveaways() {
        let app = launch("giveaways")
        XCTAssertTrue(app.staticTexts["Новогоднее колесо"].waitForExistence(timeout: 10))
    }
}
