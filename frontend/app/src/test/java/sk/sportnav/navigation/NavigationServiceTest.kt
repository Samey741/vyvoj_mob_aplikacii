package sk.sportnav.navigation

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import sk.sportnav.model.GeoPoint
import java.util.Locale

class NavigationServiceTest {

    private val service = NavigationService()
    private val point = GeoPoint(50.0755, 14.4378)
    private lateinit var originalLocale: Locale

    private val maps = "com.google.android.apps.maps"
    private val waze = "com.waze"

    private class FakeAvailability(
        private val installed: Set<String> = emptySet(),
        private val geoHandlers: Set<String> = emptySet(),
    ) : AppAvailability {
        override fun isInstalled(packageName: String) = packageName in installed
        override fun geoHandlerPackages() = geoHandlers
    }

    @Before
    fun saveLocale() {
        originalLocale = Locale.getDefault()
    }

    @After
    fun restoreLocale() {
        Locale.setDefault(originalLocale)
    }

    // --- target ---

    @Test
    fun googleMapsTarget() {
        assertEquals(
            NavigationTarget("google.navigation:q=50.075500,14.437800", maps),
            service.target(MapApp.GOOGLE_MAPS, point, "Gym"),
        )
    }

    @Test
    fun wazeTarget() {
        assertEquals(
            NavigationTarget("https://waze.com/ul?ll=50.075500,14.437800&navigate=yes", waze),
            service.target(MapApp.WAZE, point, "Gym"),
        )
    }

    @Test
    fun otherGeoTargetHasNoPackage() {
        assertEquals(
            NavigationTarget("geo:50.075500,14.437800?q=50.075500,14.437800(Gym)", null),
            service.target(MapApp.OTHER_GEO, point, "Gym"),
        )
    }

    @Test
    fun coordinatesUseDecimalPointWithSlovakLocale() {
        Locale.setDefault(Locale.forLanguageTag("sk"))
        for (app in MapApp.entries) {
            val uri = service.target(app, point, "Gym").uri
            assertEquals("no comma decimal separator in $uri", true, uri.contains("50.075500"))
            assertEquals(true, uri.contains("14.437800"))
        }
        assertEquals(
            "google.navigation:q=50.075500,14.437800",
            service.target(MapApp.GOOGLE_MAPS, point, "Gym").uri,
        )
    }

    @Test
    fun coordinatesAreRoundedToSixDecimalsAndNegativeValuesKeepSign() {
        val target = service.target(MapApp.GOOGLE_MAPS, GeoPoint(-33.8688197, 151.20929550), "x")
        assertEquals("google.navigation:q=-33.868820,151.209296", target.uri)
    }

    @Test
    fun labelWithDiacriticsAndParenthesesIsUrlEncoded() {
        val uri = service.target(MapApp.OTHER_GEO, point, "Fitness Čajka (Test) & spol.").uri
        assertEquals(
            "geo:50.075500,14.437800?q=50.075500,14.437800" +
                "(Fitness%20%C4%8Cajka%20%28Test%29%20%26%20spol.)",
            uri,
        )
    }

    // --- availableApps ---

    @Test
    fun nothingAvailable() {
        assertEquals(emptyList<MapApp>(), service.availableApps(FakeAvailability()))
    }

    @Test
    fun onlyGoogleMaps() {
        assertEquals(
            listOf(MapApp.GOOGLE_MAPS),
            service.availableApps(FakeAvailability(installed = setOf(maps))),
        )
    }

    @Test
    fun googleMapsAndWazeInFixedOrder() {
        assertEquals(
            listOf(MapApp.GOOGLE_MAPS, MapApp.WAZE),
            service.availableApps(FakeAvailability(installed = setOf(waze, maps))),
        )
    }

    @Test
    fun geoHandledOnlyByGoogleMapsAndWazeDoesNotOfferOther() {
        assertEquals(
            listOf(MapApp.GOOGLE_MAPS, MapApp.WAZE),
            service.availableApps(
                FakeAvailability(installed = setOf(maps, waze), geoHandlers = setOf(maps, waze)),
            ),
        )
        assertEquals(
            listOf(MapApp.GOOGLE_MAPS),
            service.availableApps(FakeAvailability(installed = setOf(maps), geoHandlers = setOf(maps))),
        )
    }

    @Test
    fun geoHandledByAnotherAppOffersOtherLast() {
        assertEquals(
            listOf(MapApp.GOOGLE_MAPS, MapApp.WAZE, MapApp.OTHER_GEO),
            service.availableApps(
                FakeAvailability(
                    installed = setOf(maps, waze),
                    geoHandlers = setOf(maps, "cz.seznam.mapy"),
                ),
            ),
        )
    }

    @Test
    fun onlyOtherGeoApp() {
        assertEquals(
            listOf(MapApp.OTHER_GEO),
            service.availableApps(FakeAvailability(geoHandlers = setOf("net.osmand"))),
        )
    }
}
