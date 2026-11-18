import XCTest

/// The Recherche and the fiches opened from the lists, tapped the way a finger does. Needs the
/// servers of `scripts/ios_uitest_server.sh`: the search answers the same three videos
/// ("Vidéo de test 1" to 3) for any text, and none of them is in the library at first.
final class SearchAndFicheTests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += ["-serverURL", "http://localhost:8000", "-userID", "1"]
        app.launch()
    }

    // MARK: Helpers

    private func openSearch(from tab: String = "Chaînes", button: String = "Ajouter une chaîne", entry: String = "Chercher sur YouTube") {
        app.buttons[tab].tap()
        XCTAssertTrue(app.buttons[button].waitForExistence(timeout: 5))
        app.buttons[button].tap()
        app.buttons[entry].tap()
        XCTAssertTrue(app.textFields["Rechercher sur YouTube"].waitForExistence(timeout: 5))
    }

    private func search(_ text: String) {
        let field = app.textFields["Rechercher sur YouTube"]
        field.tap()
        field.typeText(text + "\n")
    }

    private func result(_ title: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", title)).firstMatch
    }

    private func expectFiche(file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(app.buttons["Plus d'options"].waitForExistence(timeout: 5), "the fiche did not open", file: file, line: line)
    }

    // MARK: Recherche

    func testAFicheOpenedFromTheSearchStaysOpen() {
        openSearch()
        search("jazz")
        result("Vidéo de test 1").tap()
        expectFiche()
        // Still there a moment later, not replaced by an empty search.
        XCTAssertTrue(app.staticTexts["Recherche"].waitForNonExistence(timeout: 2))
        XCTAssertTrue(app.buttons["Plus d'options"].exists)
        // Back leads to the results.
        app.buttons["Retour"].tap()
        XCTAssertTrue(result("Vidéo de test 1").waitForExistence(timeout: 5))
    }

    func testLeavingAVideoWithoutTouchingAControlDoesNotIndexIt() {
        openSearch()
        search("jazz")
        result("Vidéo de test 2").tap()
        expectFiche()
        app.buttons["Retour"].tap()
        XCTAssertTrue(result("Vidéo de test 2").waitForExistence(timeout: 5))
        // The video 3 may be in the library from another test: only this row is looked at.
        XCTAssertFalse(result("Vidéo de test 2").label.contains("Dans la bibliothèque"))
    }

    func testAStarIndexesTheVideoAndItsFicheBecomesTheRealOne() {
        openSearch()
        search("jazz")
        result("Vidéo de test 3").tap()
        expectFiche()
        app.buttons["4 étoiles"].tap()
        // The fiche of the library has the Description and the discussion the candidate did not.
        XCTAssertTrue(app.staticTexts["Description"].waitForExistence(timeout: 10))
        app.buttons["Retour"].tap()
        // Back on the results, the row now says the library has it.
        let row = result("Vidéo de test 3")
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        let says = NSPredicate(format: "label CONTAINS 'Dans la bibliothèque'")
        expectation(for: says, evaluatedWith: row)
        waitForExpectations(timeout: 10)
    }

    func testTheHistoryListsTheLastSearchesAndRunsOneAgain() {
        openSearch()
        // Starts from nothing: the history of earlier runs lives in the app's defaults.
        app.textFields["Rechercher sur YouTube"].tap()
        if app.buttons["Effacer l'historique"].waitForExistence(timeout: 2) { app.buttons["Effacer l'historique"].tap() }
        search("bossa")
        XCTAssertTrue(result("Vidéo de test 1").waitForExistence(timeout: 5))
        // Touching the field shows the search just made.
        app.textFields["Rechercher sur YouTube"].tap()
        let entry = app.buttons.matching(NSPredicate(format: "label CONTAINS 'bossa' AND NOT label BEGINSWITH 'Retirer'")).firstMatch
        XCTAssertTrue(entry.waitForExistence(timeout: 5), "the history did not list the search")
        // Choosing it runs it again.
        entry.tap()
        XCTAssertTrue(result("Vidéo de test 1").waitForExistence(timeout: 5))
        // The cross takes it out of the history.
        app.textFields["Rechercher sur YouTube"].tap()
        app.buttons["Retirer « bossa » de l'historique"].tap()
        XCTAssertTrue(app.buttons["Retirer « bossa » de l'historique"].waitForNonExistence(timeout: 5))
    }

    func testTheSearchOfTheBibliothequeMenuAlsoKeepsItsFiche() {
        openSearch(from: "Bibliothèque", button: "Vues", entry: "Recherche YouTube")
        search("jazz")
        result("Vidéo de test 1").tap()
        expectFiche()
        XCTAssertTrue(app.staticTexts["Recherche"].waitForNonExistence(timeout: 2))
    }

    // MARK: Fiches from the lists

    func testAFicheOpenedFromTheBibliothequeOpensAndGoesBack() {
        app.buttons["Bibliothèque"].tap()
        let row = result("Refactoriser sans peur")
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        row.tap()
        expectFiche()
        XCTAssertTrue(app.staticTexts["Refactoriser sans peur"].exists)
        app.buttons["Retour"].tap()
        XCTAssertTrue(result("Refactoriser sans peur").waitForExistence(timeout: 5))
    }

    func testRatingAFicheKeepsTheStar() {
        app.buttons["Bibliothèque"].tap()
        let row = result("Introduction aux tests automatisés")
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        row.tap()
        expectFiche()
        app.buttons["2 étoiles"].tap()
        // The page reads the fiche again: leaving and coming back shows the same one.
        app.buttons["Retour"].tap()
        result("Introduction aux tests automatisés").tap()
        expectFiche()
        XCTAssertTrue(app.buttons["2 étoiles"].isHittable)
    }
}
