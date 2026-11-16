import SwiftUI

/// Venue categories; raw values are the slugs stored in `categories.slug`
/// (DESIGN.md section 6).
enum VenueCategory: String, CaseIterable {
    case fitness    = "posilovny-a-silove-treninky-5"
    case pool       = "bazeny-a-vodni-sporty-1"
    case yoga       = "joga-a-zdravotni-cviceni-3"
    case climbing   = "lezecke-steny-4"
    case racket     = "raketove-a-micove-sporty-7"
    case group      = "skupinove-a-tanecni-lekce-9"
    case wellness   = "wellness-a-relax-10"

    /// Localized name. The keys are defined in Localizable.xcstrings (DESIGN.md step 8).
    var displayName: String {
        switch self {
        case .fitness:  return String(localized: "category.fitness")
        case .pool:     return String(localized: "category.pool")
        case .yoga:     return String(localized: "category.yoga")
        case .climbing: return String(localized: "category.climbing")
        case .racket:   return String(localized: "category.racket")
        case .group:    return String(localized: "category.group")
        case .wellness: return String(localized: "category.wellness")
        }
    }

    /// Pin color on the map; one distinct system color per category.
    var color: Color {
        switch self {
        case .fitness:  return .orange
        case .pool:     return .blue
        case .yoga:     return .purple
        case .climbing: return .brown
        case .racket:   return .green
        case .group:    return .pink
        case .wellness: return .teal
        }
    }

    /// SF Symbols name.
    var icon: String {
        switch self {
        case .fitness:  return "dumbbell.fill"
        case .pool:     return "figure.pool.swim"
        case .yoga:     return "figure.yoga"
        case .climbing: return "figure.climbing"
        case .racket:   return "sportscourt.fill"
        case .group:    return "person.3.fill"
        case .wellness: return "leaf.fill"
        }
    }
}
