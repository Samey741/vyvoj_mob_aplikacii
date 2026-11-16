import CoreLocation
import Foundation
import SQLite

/// Source of venues for the app (DESIGN.md section 9.2).
protocol VenueRepository {
    /// Returns only venues with known GPS (`gps_pending = 0`, DESIGN.md section 8.1).
    func loadVenues() throws -> [Venue]
}

enum VenueRepositoryError: Error {
    case databaseNotFound(String)
}

/// Reads venues from the bundled SQLite database (schema: DESIGN.md section 3.3).
struct SQLiteVenueRepository: VenueRepository {
    let databaseURL: URL

    init(databaseURL: URL) {
        self.databaseURL = databaseURL
    }

    /// Repository over `venues.sqlite` from the given bundle (the app bundle by default).
    static func bundled(in bundle: Bundle = .main,
                        resource: String = "venues",
                        withExtension ext: String = "sqlite") throws -> SQLiteVenueRepository {
        guard let url = bundle.url(forResource: resource, withExtension: ext) else {
            throw VenueRepositoryError.databaseNotFound("\(resource).\(ext)")
        }
        return SQLiteVenueRepository(databaseURL: url)
    }

    func loadVenues() throws -> [Venue] {
        let db = try Connection(databaseURL.path, readonly: true)

        let categoriesByVenue = try loadCategories(db)
        let hoursByVenue = try loadOpeningHours(db)

        // Only venues with GPS (section 8.1). The lat/lon NOT NULL checks are a safety net:
        // coordinate is non-optional.
        let venueSQL = """
            SELECT id, name, street, city, lat, lon, phone, website
            FROM venues
            WHERE COALESCE(gps_pending, 0) = 0 AND lat IS NOT NULL AND lon IS NOT NULL
            ORDER BY id
            """

        var venues: [Venue] = []
        for row in try db.prepare(venueSQL) {
            guard let id = Self.int(row[0]),
                  let name = Self.string(row[1]),
                  let lat = Self.double(row[4]),
                  let lon = Self.double(row[5]) else {
                continue
            }
            venues.append(Venue(
                id: id,
                name: name,
                street: Self.string(row[2]) ?? "",   // NULL -> "" (section 8.11)
                city: Self.string(row[3]) ?? "",     // NULL -> "" (section 8.11)
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon),
                categories: categoriesByVenue[id] ?? [],
                openingHours: hoursByVenue[id] ?? [],
                phone: Self.string(row[6]),
                website: Self.string(row[7])
            ))
        }
        return venues
    }

    // MARK: - Private helpers

    /// venue_id -> known categories, in link insertion order. Unknown slugs are skipped
    /// (section 8.2); the venue itself is still loaded.
    private func loadCategories(_ db: Connection) throws -> [Int: [VenueCategory]] {
        let sql = """
            SELECT vc.venue_id, c.slug
            FROM venue_categories vc
            JOIN categories c ON c.id = vc.category_id
            ORDER BY vc.venue_id, vc.rowid
            """
        var result: [Int: [VenueCategory]] = [:]
        for row in try db.prepare(sql) {
            guard let venueId = Self.int(row[0]),
                  let slug = Self.string(row[1]),
                  let category = VenueCategory(rawValue: slug) else {
                continue
            }
            var list = result[venueId] ?? []
            if !list.contains(category) {
                list.append(category)
            }
            result[venueId] = list
        }
        return result
    }

    /// venue_id -> schedule rows in insertion order. Rows are kept as stored: `closes < opens`
    /// is valid and several rows per day are allowed (section 8.10). Rows with an
    /// unrecognised day or missing times are skipped.
    private func loadOpeningHours(_ db: Connection) throws -> [Int: [DaySchedule]] {
        let sql = """
            SELECT venue_id, day, opens, closes
            FROM opening_hours
            ORDER BY venue_id, rowid
            """
        var result: [Int: [DaySchedule]] = [:]
        for row in try db.prepare(sql) {
            guard let venueId = Self.int(row[0]),
                  let dayString = Self.string(row[1]),
                  let day = Weekday(rawValue: dayString),
                  let opens = Self.string(row[2]),
                  let closes = Self.string(row[3]) else {
                continue
            }
            var list = result[venueId] ?? []
            list.append(DaySchedule(day: day, opens: opens, closes: closes))
            result[venueId] = list
        }
        return result
    }

    // SQLite.swift returns each column as `Binding?`: Int64, Double, String, Blob or nil.

    private static func int(_ value: Binding?) -> Int? {
        if let integer = value as? Int64 {
            return Int(integer)
        }
        return nil
    }

    private static func double(_ value: Binding?) -> Double? {
        if let real = value as? Double {
            return real
        }
        if let integer = value as? Int64 {
            return Double(integer)
        }
        return nil
    }

    private static func string(_ value: Binding?) -> String? {
        return value as? String
    }
}
