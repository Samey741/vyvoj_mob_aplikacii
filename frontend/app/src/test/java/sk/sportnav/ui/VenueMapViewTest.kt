package sk.sportnav.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.maplibre.geojson.Point
import sk.sportnav.model.Venue
import sk.sportnav.model.VenueCategory

class VenueMapViewTest {

    private fun venue(id: Int, lat: Double, lon: Double, vararg categories: VenueCategory) = Venue(
        id = id, name = "V$id", street = "", city = "", latitude = lat, longitude = lon,
        categories = categories.toList(), openingHours = emptyList(), phone = null, website = null,
    )

    @Test
    fun noVenuesGiveAnEmptyCollection() {
        assertTrue(buildVenueFeatures(emptyList()).features().orEmpty().isEmpty())
    }

    @Test
    fun featureHasLongitudeLatitudeOrderIdAndColor() {
        val collection = buildVenueFeatures(listOf(venue(7, 50.0755, 14.4378, VenueCategory.POOL)))

        val feature = collection.features().orEmpty().single()
        val point = feature.geometry() as Point
        assertEquals(14.4378, point.longitude(), 0.0)
        assertEquals(50.0755, point.latitude(), 0.0)
        assertEquals(7, feature.getNumberProperty("id").toInt())
        assertEquals("#1E88E5", feature.getStringProperty("color"))
    }

    @Test
    fun colorIsThatOfTheMainCategory() {
        // FITNESS is declared before YOGA, so it wins whatever the list order.
        val feature = buildVenueFeatures(listOf(venue(1, 0.0, 0.0, VenueCategory.YOGA, VenueCategory.FITNESS)))
            .features().orEmpty().single()
        assertEquals(VenueCategory.FITNESS.colorHex, feature.getStringProperty("color"))
    }

    @Test
    fun venueWithoutKnownCategoryIsGrey() {
        val feature = buildVenueFeatures(listOf(venue(1, 0.0, 0.0))).features().orEmpty().single()
        assertEquals("#757575", feature.getStringProperty("color"))
    }

    @Test
    fun attributionStartsRightOfTheLogo() {
        // Logo: 8 dp margin + 88 dp width.
        for (density in listOf(1f, 2.625f, 3f)) {
            assertTrue(attributionStartMarginPx(density) >= ((8 + 88) * density).toInt())
        }
    }

    @Test
    fun oneFeaturePerVenueInOrder() {
        val features = buildVenueFeatures(listOf(venue(3, 1.0, 2.0), venue(1, 3.0, 4.0))).features().orEmpty()
        assertEquals(listOf(3, 1), features.map { it.getNumberProperty("id").toInt() })
    }
}
