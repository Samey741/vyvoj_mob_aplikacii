package sk.sportnav.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class FilterSheetTest {

    @Test
    fun floatNoiseSnapsToTheGrid() {
        assertEquals(5.0, snapToHalfKm(4.9999995f), 0.0)
        assertEquals(5.0, snapToHalfKm(5.0000005f), 0.0)
        assertEquals(12.5, snapToHalfKm(12.499999f), 0.0)
    }

    @Test
    fun valuesBetweenGridPointsRoundToNearest() {
        assertEquals(1.0, snapToHalfKm(1.2f), 0.0)
        assertEquals(1.5, snapToHalfKm(1.3f), 0.0)
        assertEquals(1.5, snapToHalfKm(1.7f), 0.0)
    }

    @Test
    fun resultStaysInRange() {
        assertEquals(0.5, snapToHalfKm(0.5f), 0.0)
        assertEquals(0.5, snapToHalfKm(0.1f), 0.0)
        assertEquals(20.0, snapToHalfKm(20f), 0.0)
        assertEquals(20.0, snapToHalfKm(25f), 0.0)
    }
}
