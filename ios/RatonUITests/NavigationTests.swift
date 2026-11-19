import XCTest

/// Taps the tab bar and the menus the way a finger does. Needs the servers of
/// `scripts/ios_uitest_server.sh` (demo data, a YouTube that answers three fixed videos, front on
/// localhost:8000); the app is pointed at them by launch arguments.
final class NavigationTests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += ["-serverURL", "http://localhost:8000", "-userID", "1"]
        app.launch()
    }

    private func openTab(_ label: String, shows title: String) {
        app.buttons[label].tap()
        XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 10), "\(label) did not open \(title)")
    }

    func testEveryTabOpensItsPage() {
        openTab("Chaînes", shows: "Chaînes")
        openTab("Bibliothèque", shows: "Bibliothèque")
        openTab("Playlists", shows: "Playlists")
        openTab("Paramètres", shows: "Paramètres")
        // Raton's line changes at each visit: the Accueil is told by the previous page going away.
        app.buttons["Accueil"].tap()
        XCTAssertTrue(app.staticTexts["Paramètres"].waitForNonExistence(timeout: 5))
    }

    func testLibraryMenuOpensTheHistorique() {
        openTab("Bibliothèque", shows: "Bibliothèque")
        app.buttons["Vues"].tap()
        app.buttons["Historique"].tap()
        XCTAssertTrue(app.staticTexts["Historique"].waitForExistence(timeout: 5))
    }

    func testATabKeepsItsPageUntilItsIconIsTappedAgain() {
        openTab("Bibliothèque", shows: "Bibliothèque")
        app.buttons["Vues"].tap()
        app.buttons["Historique"].tap()
        XCTAssertTrue(app.staticTexts["Historique"].waitForExistence(timeout: 5))
        openTab("Playlists", shows: "Playlists")
        // Back on the tab: the page pushed there is still the one shown.
        openTab("Bibliothèque", shows: "Historique")
        // A second tap on the icon of the tab on screen goes back to its base page.
        openTab("Bibliothèque", shows: "Bibliothèque")
        XCTAssertFalse(app.staticTexts["Historique"].exists)
    }
}
