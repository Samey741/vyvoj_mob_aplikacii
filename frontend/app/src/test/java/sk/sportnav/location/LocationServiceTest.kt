package sk.sportnav.location

import android.Manifest
import android.app.Application
import android.content.Context
import android.location.Location
import android.location.LocationManager
import android.os.Looper
import org.robolectric.RuntimeEnvironment
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import sk.sportnav.model.GeoPoint

@RunWith(RobolectricTestRunner::class)
class LocationServiceTest {

    private lateinit var app: Application
    private lateinit var manager: LocationManager

    @Before
    fun setUp() {
        app = RuntimeEnvironment.getApplication()
        manager = app.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    }

    private fun location(provider: String, lat: Double, lon: Double, time: Long) =
        Location(provider).apply {
            latitude = lat
            longitude = lon
            this.time = time
        }

    @Test
    fun withoutPermissionEmitsNull() = runBlocking {
        assertNull(LocationService(app).locations().first())
    }

    @Test
    fun emitsMostRecentLastKnownLocationFirst() = runBlocking {
        shadowOf(app).grantPermissions(Manifest.permission.ACCESS_FINE_LOCATION)
        val shadow = shadowOf(manager)
        shadow.setProviderEnabled(LocationManager.GPS_PROVIDER, true)
        shadow.setProviderEnabled(LocationManager.NETWORK_PROVIDER, true)
        shadow.setLastKnownLocation(LocationManager.GPS_PROVIDER, location(LocationManager.GPS_PROVIDER, 1.0, 2.0, 1_000))
        shadow.setLastKnownLocation(LocationManager.NETWORK_PROVIDER, location(LocationManager.NETWORK_PROVIDER, 3.0, 4.0, 2_000))

        assertEquals(GeoPoint(3.0, 4.0), LocationService(app).locations().first())
    }

    @Test
    fun updatesAreRemovedWhenCollectionStops() = runBlocking {
        shadowOf(app).grantPermissions(Manifest.permission.ACCESS_COARSE_LOCATION)
        val shadow = shadowOf(manager)
        shadow.setProviderEnabled(LocationManager.NETWORK_PROVIDER, true)
        shadow.setLastKnownLocation(LocationManager.NETWORK_PROVIDER, location(LocationManager.NETWORK_PROVIDER, 5.0, 6.0, 1_000))

        val emitted = LocationService(app).locations().take(1).toList()

        assertEquals(listOf<GeoPoint?>(GeoPoint(5.0, 6.0)), emitted)
        assertTrue(shadow.getLocationUpdateListeners().isEmpty())
    }

    @Test
    fun updateAfterLastKnownIsTheLatestValue() = runBlocking {
        shadowOf(app).grantPermissions(Manifest.permission.ACCESS_FINE_LOCATION)
        val shadow = shadowOf(manager)
        shadow.setProviderEnabled(LocationManager.GPS_PROVIDER, true)
        shadow.setLastKnownLocation(LocationManager.GPS_PROVIDER, location(LocationManager.GPS_PROVIDER, 1.0, 2.0, 1_000))

        val collected = mutableListOf<GeoPoint?>()
        LocationService(app).locations()
            .onEach { point ->
                collected += point
                if (collected.size == 1) {
                    // The listener must already be registered once the last known point is out.
                    assertEquals(1, shadow.getLocationUpdateListeners().size)
                    shadow.simulateLocation(location(LocationManager.GPS_PROVIDER, 7.0, 8.0, 2_000))
                    shadowOf(Looper.getMainLooper()).idle()
                }
            }
            .take(2)
            .toList()

        assertEquals(listOf<GeoPoint?>(GeoPoint(1.0, 2.0), GeoPoint(7.0, 8.0)), collected)
    }
}
