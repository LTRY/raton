import XCTest

/// Taps the tab bar and the menus the way a finger does. Needs the demo back and front
/// (`make demo`, front on localhost:8000); the app is pointed at them by launch arguments.
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
        XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 5), "\(label) did not open \(title)")
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

    /// A video found on YouTube opens its page and stays on it (the page used to be replaced by an empty
    /// Recherche). Needs the demo back to reach YouTube, so it is skipped when no result comes back.
    func testAFicheOpenedFromTheSearchStaysOpen() throws {
        openTab("Chaînes", shows: "Chaînes")
        app.buttons["Ajouter une chaîne"].tap()
        app.buttons["Chercher sur YouTube"].tap()
        let field = app.textFields["Rechercher sur YouTube"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText("jazz\n")
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS 'vues'")).firstMatch
        try XCTSkipUnless(row.waitForExistence(timeout: 30), "YouTube did not answer")
        row.tap()
        XCTAssertTrue(app.buttons["Plus d'options"].waitForExistence(timeout: 5), "the fiche did not open")
        // Still there a moment later, not replaced by the search.
        XCTAssertTrue(app.staticTexts["Recherche"].waitForNonExistence(timeout: 2))
        XCTAssertTrue(app.buttons["Plus d'options"].exists)
        // Back leads to the results, not to an empty search.
        app.buttons["Retour"].tap()
        XCTAssertTrue(row.waitForExistence(timeout: 5))
    }
}
