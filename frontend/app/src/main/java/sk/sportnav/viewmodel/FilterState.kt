package sk.sportnav.viewmodel

import sk.sportnav.model.VenueCategory

/** Map filter (DESIGN.md 8.7). */
data class FilterState(
    /** Empty = all categories; a venue matches when it has at least one of them. */
    val categories: Set<VenueCategory> = emptySet(),
    /** Maximum distance from the user in km, 0.5 ... 20. Ignored while the user location is unknown. */
    val maxDistanceKm: Double = 5.0,
)
