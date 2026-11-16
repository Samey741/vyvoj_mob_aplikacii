package sk.sportnav.location

import org.junit.Assert.assertEquals
import org.junit.Test
import sk.sportnav.model.GeoPoint

class DistanceTest {

    private val prague = GeoPoint(50.0755, 14.4378)
    private val brno = GeoPoint(49.1951, 16.6068)

    @Test
    fun samePointIsZero() {
        assertEquals(0.0, distanceMeters(prague, prague), 0.0)
    }

    @Test
    fun pragueToBrnoIsAbout185Km() {
        assertEquals(185_000.0, distanceMeters(prague, brno), 1_000.0)
    }

    @Test
    fun isSymmetric() {
        assertEquals(distanceMeters(prague, brno), distanceMeters(brno, prague), 1e-6)
    }

    @Test
    fun oneDegreeOfLatitudeIsAbout111Km() {
        val d = distanceMeters(GeoPoint(0.0, 0.0), GeoPoint(1.0, 0.0))
        assertEquals(111_195.0, d, 10.0)
    }

    @Test
    fun antipodalPointsDoNotProduceNaN() {
        val d = distanceMeters(GeoPoint(0.0, 0.0), GeoPoint(0.0, 180.0))
        assertEquals(Math.PI * 6_371_000.0, d, 1.0)
    }
}
