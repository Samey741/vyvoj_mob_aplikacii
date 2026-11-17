package sk.sportnav.location

import sk.sportnav.model.GeoPoint
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

private const val EARTH_RADIUS_METERS = 6_371_000.0

/** Great-circle distance between [a] and [b] in metres (Haversine, Earth radius 6 371 000 m; DESIGN.md 8.7). */
fun distanceMeters(a: GeoPoint, b: GeoPoint): Double {
    val lat1 = Math.toRadians(a.latitude)
    val lat2 = Math.toRadians(b.latitude)
    val dLat = lat2 - lat1
    val dLon = Math.toRadians(b.longitude - a.longitude)
    val h = sin(dLat / 2) * sin(dLat / 2) + cos(lat1) * cos(lat2) * sin(dLon / 2) * sin(dLon / 2)
    // min(1.0, ...) guards against rounding pushing sqrt(h) just above 1 for antipodal points.
    return 2 * EARTH_RADIUS_METERS * asin(min(1.0, sqrt(h)))
}
