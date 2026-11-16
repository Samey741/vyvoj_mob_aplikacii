package sk.sportnav.navigation

import sk.sportnav.model.GeoPoint
import java.net.URLEncoder
import java.util.Locale

/** External map apps the user can navigate with, in display order (DESIGN.md 5.4). */
enum class MapApp { GOOGLE_MAPS, WAZE, OTHER_GEO }

/** What the device has installed; implemented over PackageManager in the app, faked in tests. */
interface AppAvailability {
    fun isInstalled(packageName: String): Boolean

    /** Packages that can open a `geo:` URI. */
    fun geoHandlerPackages(): Set<String>
}

/** [uri] to open with ACTION_VIEW; [packageName] is set as the intent package, or null to let the system choose. */
data class NavigationTarget(val uri: String, val packageName: String?)

class NavigationService {

    /** Available apps in the order GOOGLE_MAPS, WAZE, OTHER_GEO. Empty if none is available. */
    fun availableApps(availability: AppAvailability): List<MapApp> {
        val apps = mutableListOf<MapApp>()
        if (availability.isInstalled(GOOGLE_MAPS_PACKAGE)) apps += MapApp.GOOGLE_MAPS
        if (availability.isInstalled(WAZE_PACKAGE)) apps += MapApp.WAZE
        // "Other" only counts a geo: handler that is neither Google Maps nor Waze.
        if ((availability.geoHandlerPackages() - GOOGLE_MAPS_PACKAGE - WAZE_PACKAGE).isNotEmpty()) {
            apps += MapApp.OTHER_GEO
        }
        return apps
    }

    /** Coordinates always use a decimal point with 6 decimals (Locale.ROOT), whatever the device locale. */
    fun target(app: MapApp, point: GeoPoint, label: String): NavigationTarget {
        val lat = coordinate(point.latitude)
        val lon = coordinate(point.longitude)
        return when (app) {
            MapApp.GOOGLE_MAPS -> NavigationTarget("google.navigation:q=$lat,$lon", GOOGLE_MAPS_PACKAGE)
            MapApp.WAZE -> NavigationTarget("https://waze.com/ul?ll=$lat,$lon&navigate=yes", WAZE_PACKAGE)
            MapApp.OTHER_GEO -> NavigationTarget("geo:$lat,$lon?q=$lat,$lon(${encode(label)})", null)
        }
    }

    private fun coordinate(value: Double): String = String.format(Locale.ROOT, "%.6f", value)

    // URLEncoder is form encoding and writes a space as '+'; inside a URI query %20 is the right form.
    private fun encode(label: String): String = URLEncoder.encode(label, "UTF-8").replace("+", "%20")

    companion object {
        const val GOOGLE_MAPS_PACKAGE = "com.google.android.apps.maps"
        const val WAZE_PACKAGE = "com.waze"
    }
}
