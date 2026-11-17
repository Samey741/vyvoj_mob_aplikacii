package sk.sportnav.location

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import androidx.core.content.ContextCompat
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate
import sk.sportnav.model.GeoPoint

/** User location from the framework [LocationManager], no Google Play Services (DESIGN.md 8.14). */
class LocationService(context: Context) {

    private val appContext = context.applicationContext
    private val locationManager = appContext.getSystemService(Context.LOCATION_SERVICE) as? LocationManager

    /**
     * Emits the last known location first (if there is one), then every update from the enabled
     * GPS / network providers (minTime 5 s, minDistance 20 m). Without location permission (or
     * without a [LocationManager]) it emits a single `null`. Updates are removed when the collector
     * is cancelled.
     */
    fun locations(): Flow<GeoPoint?> = callbackFlow {
        val manager = locationManager
        if (manager == null || !hasLocationPermission()) {
            trySend(null)
            awaitClose { }
            return@callbackFlow
        }

        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                trySend(location.toGeoPoint())
            }

            // Abstract before API 30; kept so the listener compiles and runs on API 26-29.
            @Deprecated("Deprecated in Java")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
            override fun onProviderEnabled(provider: String) = Unit
            override fun onProviderDisabled(provider: String) = Unit
        }

        // With only the approximate permission, GPS_PROVIDER throws SecurityException; that provider is skipped.
        val providers = PROVIDERS.filter { provider ->
            try {
                manager.isProviderEnabled(provider)
            } catch (_: SecurityException) {
                false
            } catch (_: IllegalArgumentException) {
                false
            }
        }

        // The last known location goes out BEFORE the listener is registered, so a fresh fix
        // (possibly delivered on the main Looper while this block still runs) can never be
        // overwritten by the stale one under conflate().
        var lastKnown: Location? = null
        for (provider in providers) {
            try {
                val candidate = manager.getLastKnownLocation(provider)
                if (candidate != null && (lastKnown == null || candidate.time > lastKnown.time)) {
                    lastKnown = candidate
                }
            } catch (_: SecurityException) {
                // permission does not cover this provider
            } catch (_: IllegalArgumentException) {
                // provider not available on this device
            }
        }
        if (lastKnown != null) trySend(lastKnown.toGeoPoint())

        var registeredCount = 0
        for (provider in providers) {
            try {
                manager.requestLocationUpdates(
                    provider, MIN_TIME_MS, MIN_DISTANCE_M, listener, Looper.getMainLooper(),
                )
                registeredCount++
            } catch (_: SecurityException) {
                // permission does not cover this provider
            } catch (_: IllegalArgumentException) {
                // provider not available on this device
            }
        }
        if (registeredCount == 0) trySend(null)

        awaitClose { manager.removeUpdates(listener) }
    }.conflate()

    private fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(appContext, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(appContext, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun Location.toGeoPoint() = GeoPoint(latitude, longitude)

    private companion object {
        val PROVIDERS = listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
        const val MIN_TIME_MS = 5_000L
        const val MIN_DISTANCE_M = 20f
    }
}
