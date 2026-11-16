import SQLite
import UIKit
import XCTest
@testable import SportNav

/// Tests for SQLiteVenueRepository over Fixtures/test_venues.sqlite (DESIGN.md section 11.2).
///
/// Fixture contents (created by the backend, step 3):
/// - ids 1, 2, 4, 5, 6: normal venues; 2 has two categories and an overnight Friday block,
///   5 has two blocks on Monday
/// - id 3: no hours, phone or website
/// - id 7: gps_pending = 1, lat/lon NULL (must not be loaded)
/// - id 8: only an unknown category, so no venue_categories row
/// - id 9: one known and one unknown category, so only one venue_categories row
final class VenueRepositoryTests: XCTestCase {

    private var temporaryFiles: [URL] = []

    override func tearDown() {
        for url in temporaryFiles {
            try? FileManager.default.removeItem(at: url)
        }
        temporaryFiles = []
        super.tearDown()
    }

    // MARK: - Helpers

    /// With synchronized folders the fixture may be copied either into a "Fixtures"
    /// subdirectory or flat into the bundle root, so both locations are tried.
    private func fixtureURL(file: StaticString = #filePath, line: UInt = #line) throws -> URL {
        let bundle = Bundle(for: VenueRepositoryTests.self)
        if let url = bundle.url(forResource: "test_venues", withExtension: "sqlite", subdirectory: "Fixtures") {
            return url
        }
        if let url = bundle.url(forResource: "test_venues", withExtension: "sqlite") {
            return url
        }
        XCTFail("test_venues.sqlite not found in the test bundle", file: file, line: line)
        throw VenueRepositoryError.databaseNotFound("test_venues.sqlite")
    }

    private func loadFixtureVenues() throws -> [Venue] {
        let repository = SQLiteVenueRepository(databaseURL: try fixtureURL())
        return try repository.loadVenues()
    }

    private func venue(_ id: Int, in venues: [Venue],
                       file: StaticString = #filePath, line: UInt = #line) throws -> Venue {
        guard let found = venues.first(where: { $0.id == id }) else {
            XCTFail("venue \(id) was not loaded", file: file, line: line)
            throw VenueRepositoryError.databaseNotFound("venue \(id)")
        }
        return found
    }

    /// Creates a temporary SQLite file with the section 3.3 schema and runs the given SQL on it.
    private func makeTemporaryDatabase(populate sql: String) throws -> URL {
        let url = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("sportnav-test-\(UUID().uuidString).sqlite")
        temporaryFiles.append(url)

        let schema = """
            CREATE TABLE venues (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, street TEXT, city TEXT,
                lat REAL, lon REAL, phone TEXT, website TEXT, gps_source TEXT,
                gps_pending INTEGER DEFAULT 0);
            CREATE TABLE categories (id INTEGER PRIMARY KEY, slug TEXT NOT NULL, name TEXT NOT NULL);
            CREATE TABLE venue_categories (venue_id INTEGER, category_id INTEGER);
            CREATE TABLE opening_hours (venue_id INTEGER, day TEXT, opens TEXT, closes TEXT);
            """
        let db = try Connection(url.path)
        try db.execute(schema)
        try db.execute(sql)
        return url
    }

    // MARK: - Loading and GPS filter (section 8.1)

    func testLoadsAllVenuesWithGPS() throws {
        let venues = try loadFixtureVenues()

        XCTAssertEqual(venues.count, 8)
        XCTAssertEqual(venues.map { $0.id }, [1, 2, 3, 4, 5, 6, 8, 9])
    }

    func testOmitsVenueWithGPSPending() throws {
        let venues = try loadFixtureVenues()

        XCTAssertFalse(venues.contains(where: { $0.id == 7 }))
    }

    func testMapsBasicFieldsOfVenue1() throws {
        let venue1 = try venue(1, in: try loadFixtureVenues())

        XCTAssertEqual(venue1.name, "Legion Gym")
        XCTAssertEqual(venue1.street, "Husova 100")
        XCTAssertEqual(venue1.city, "Jaroměř")
        XCTAssertEqual(venue1.coordinate.latitude, 50.3563, accuracy: 0.00001)
        XCTAssertEqual(venue1.coordinate.longitude, 15.9223, accuracy: 0.00001)
        XCTAssertEqual(venue1.phone, "+420 606 182 647")
        XCTAssertEqual(venue1.website, "http://legiongym.cz/")
    }

    func testVenueWithoutPhoneWebsiteAndHours() throws {
        let venue3 = try venue(3, in: try loadFixtureVenues())

        XCTAssertEqual(venue3.name, "Joga Studio Lotos")
        XCTAssertNil(venue3.phone)
        XCTAssertNil(venue3.website)
        XCTAssertEqual(venue3.openingHours, [])
        XCTAssertEqual(venue3.categories, [.yoga])
        XCTAssertEqual(venue3.coordinate.latitude, 48.7164, accuracy: 0.00001)
        XCTAssertEqual(venue3.coordinate.longitude, 21.2611, accuracy: 0.00001)
    }

    // MARK: - Categories

    func testMapsCategories() throws {
        let venues = try loadFixtureVenues()

        XCTAssertEqual(try venue(1, in: venues).categories, [.fitness])
        XCTAssertEqual(try venue(2, in: venues).categories, [.pool, .wellness])
        XCTAssertEqual(try venue(3, in: venues).categories, [.yoga])
        XCTAssertEqual(try venue(4, in: venues).categories, [.climbing])
        XCTAssertEqual(try venue(5, in: venues).categories, [.racket, .group])
        XCTAssertEqual(try venue(6, in: venues).categories, [.group])
    }

    // MARK: - Opening hours (section 8.10)

    func testMapsOpeningHoursOfVenue1() throws {
        let venue1 = try venue(1, in: try loadFixtureVenues())

        XCTAssertEqual(venue1.openingHours, [
            DaySchedule(day: .mon, opens: "06:00", closes: "22:00"),
            DaySchedule(day: .tue, opens: "06:00", closes: "22:00"),
            DaySchedule(day: .wed, opens: "06:00", closes: "22:00"),
            DaySchedule(day: .thu, opens: "06:00", closes: "22:00"),
            DaySchedule(day: .fri, opens: "06:00", closes: "22:00"),
            DaySchedule(day: .sat, opens: "08:00", closes: "20:00"),
        ])
    }

    func testKeepsOvernightBlockUnchanged() throws {
        let venue2 = try venue(2, in: try loadFixtureVenues())

        XCTAssertEqual(venue2.openingHours.count, 5)
        let friday = venue2.openingHours.filter { $0.day == .fri }
        XCTAssertEqual(friday, [DaySchedule(day: .fri, opens: "06:00", closes: "02:00")])
        guard let fridayBlock = friday.first else { return XCTFail("expected a Friday block") }
        XCTAssertTrue(fridayBlock.closes < fridayBlock.opens)
    }

    func testKeepsTwoBlocksOnOneDay() throws {
        let venue5 = try venue(5, in: try loadFixtureVenues())

        XCTAssertEqual(venue5.openingHours, [
            DaySchedule(day: .mon, opens: "07:00", closes: "12:00"),
            DaySchedule(day: .mon, opens: "14:00", closes: "21:00"),
            DaySchedule(day: .tue, opens: "07:00", closes: "21:00"),
        ])
    }

    func testMapsSevenDayOpeningHoursOfVenue4() throws {
        let venue4 = try venue(4, in: try loadFixtureVenues())

        XCTAssertEqual(venue4.openingHours.map { $0.day }, Weekday.allCases)
        for schedule in venue4.openingHours {
            XCTAssertEqual(schedule.opens, "09:00")
            XCTAssertEqual(schedule.closes, "23:00")
        }
    }

    // MARK: - Unknown categories (section 8.2)

    func testVenueWithOnlyUnknownCategoryLoadsWithNoCategories() throws {
        let venue8 = try venue(8, in: try loadFixtureVenues())

        XCTAssertEqual(venue8.name, "Bowling Klub Neznámy")
        XCTAssertEqual(venue8.categories, [])
        XCTAssertEqual(venue8.street, "Dlhá 3")
        XCTAssertEqual(venue8.city, "Trnava")
        XCTAssertEqual(venue8.coordinate.latitude, 48.3774, accuracy: 0.00001)
        XCTAssertEqual(venue8.coordinate.longitude, 17.5883, accuracy: 0.00001)
        XCTAssertEqual(venue8.openingHours, [
            DaySchedule(day: .sat, opens: "12:00", closes: "23:00"),
            DaySchedule(day: .sun, opens: "12:00", closes: "23:00"),
        ])
    }

    func testVenueWithKnownAndUnknownCategoryKeepsOnlyKnown() throws {
        let venue9 = try venue(9, in: try loadFixtureVenues())

        XCTAssertEqual(venue9.name, "Fitness Plus")
        XCTAssertEqual(venue9.categories, [.fitness])
        XCTAssertEqual(venue9.openingHours, [
            DaySchedule(day: .mon, opens: "00:00", closes: "23:59"),
        ])
        XCTAssertEqual(venue9.phone, "+421 52 555 0109")
        XCTAssertEqual(venue9.website, "https://fitnessplus.example/")
    }

    func testUnknownCategorySlugInDatabaseIsSkipped() throws {
        let url = try makeTemporaryDatabase(populate: """
            INSERT INTO venues (id, name, street, city, lat, lon, gps_pending)
                VALUES (1, 'Test Venue', 'Main 1', 'Town', 48.0, 17.0, 0);
            INSERT INTO categories (id, slug, name) VALUES
                (1, 'wellness-a-relax-10', 'Wellness a relax'),
                (2, 'some-future-category-99', 'Future');
            INSERT INTO venue_categories (venue_id, category_id) VALUES (1, 2), (1, 1);
            """)

        let venues = try SQLiteVenueRepository(databaseURL: url).loadVenues()

        XCTAssertEqual(venues.count, 1)
        guard let loaded = venues.first else { return XCTFail("expected a venue") }
        XCTAssertEqual(loaded.categories, [.wellness])
    }

    // MARK: - NULL street / city (section 8.11)

    func testFixtureVenuesHaveStreetAndCity() throws {
        // Documents that no fixture venue has NULL street/city; the NULL case is covered below.
        for venue in try loadFixtureVenues() {
            XCTAssertFalse(venue.street.isEmpty, "venue \(venue.id)")
            XCTAssertFalse(venue.city.isEmpty, "venue \(venue.id)")
        }
    }

    func testNullStreetAndCityMapToEmptyStrings() throws {
        let url = try makeTemporaryDatabase(populate: """
            INSERT INTO venues (id, name, street, city, lat, lon, phone, website, gps_pending)
                VALUES (1, 'No Address', NULL, NULL, 48.5, 17.5, NULL, NULL, 0);
            INSERT INTO venues (id, name, street, city, lat, lon, gps_pending)
                VALUES (2, 'No Street', NULL, 'Brno', 49.2, 16.6, 0);
            """)

        let venues = try SQLiteVenueRepository(databaseURL: url).loadVenues()

        XCTAssertEqual(venues.map { $0.id }, [1, 2])
        guard venues.count == 2 else { return XCTFail("expected 2 venues, got \(venues.count)") }
        let noAddress = venues[0]
        let noStreet = venues[1]
        XCTAssertEqual(noAddress.street, "")
        XCTAssertEqual(noAddress.city, "")
        XCTAssertNil(noAddress.phone)
        XCTAssertNil(noAddress.website)
        XCTAssertEqual(noStreet.street, "")
        XCTAssertEqual(noStreet.city, "Brno")
    }

    // MARK: - VenueCategory (section 6)

    func testVenueCategorySlugsAndDisplayAttributes() {
        XCTAssertEqual(VenueCategory.allCases.count, 7)
        XCTAssertEqual(VenueCategory.fitness.rawValue, "posilovny-a-silove-treninky-5")
        XCTAssertEqual(VenueCategory.pool.rawValue, "bazeny-a-vodni-sporty-1")
        XCTAssertEqual(VenueCategory.yoga.rawValue, "joga-a-zdravotni-cviceni-3")
        XCTAssertEqual(VenueCategory.climbing.rawValue, "lezecke-steny-4")
        XCTAssertEqual(VenueCategory.racket.rawValue, "raketove-a-micove-sporty-7")
        XCTAssertEqual(VenueCategory.group.rawValue, "skupinove-a-tanecni-lekce-9")
        XCTAssertEqual(VenueCategory.wellness.rawValue, "wellness-a-relax-10")

        for category in VenueCategory.allCases {
            XCTAssertFalse(category.displayName.isEmpty, "\(category)")
            XCTAssertNotNil(UIImage(systemName: category.icon), "missing SF Symbol \(category.icon)")
        }
    }
}
