import CoreLocation
import Foundation

/// Day of the week as stored in the `opening_hours.day` column (DESIGN.md section 9.2).
enum Weekday: String, CaseIterable {
    case mon, tue, wed, thu, fri, sat, sun
}

/// One opening block that STARTS on `day` (DESIGN.md section 8.10).
/// `closes < opens` means the block ends after midnight on the following day;
/// the values are kept exactly as stored. A day may have several blocks.
struct DaySchedule: Equatable {
    let day: Weekday
    let opens: String   // "06:00"
    let closes: String  // "22:00"
}

/// A venue with known GPS coordinates (DESIGN.md section 6, section 8.1).
struct Venue: Identifiable {
    let id: Int
    let name: String
    /// Empty string when the database holds NULL (DESIGN.md section 8.11).
    let street: String
    /// Empty string when the database holds NULL (DESIGN.md section 8.11).
    let city: String
    let coordinate: CLLocationCoordinate2D
    let categories: [VenueCategory]
    let openingHours: [DaySchedule]
    let phone: String?
    let website: String?
}
