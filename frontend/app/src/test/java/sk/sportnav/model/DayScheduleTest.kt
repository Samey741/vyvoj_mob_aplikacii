package sk.sportnav.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DayScheduleTest {

    private val hours = listOf(
        DaySchedule(Weekday.MON, "07:00", "12:00"),
        DaySchedule(Weekday.MON, "14:00", "21:00"),
        DaySchedule(Weekday.TUE, "07:00", "21:00"),
        DaySchedule(Weekday.FRI, "22:00", "02:00"),
    )

    @Test
    fun returnsOnlyRowsOfGivenDayIncludingMultipleBlocks() {
        assertEquals(
            listOf(DaySchedule(Weekday.MON, "07:00", "12:00"), DaySchedule(Weekday.MON, "14:00", "21:00")),
            todaySchedule(hours, Weekday.MON),
        )
        assertEquals(listOf(DaySchedule(Weekday.TUE, "07:00", "21:00")), todaySchedule(hours, Weekday.TUE))
    }

    @Test
    fun closesBeforeOpensIsLeftUntouched() {
        assertEquals(listOf(DaySchedule(Weekday.FRI, "22:00", "02:00")), todaySchedule(hours, Weekday.FRI))
    }

    @Test
    fun dayWithoutRowsGivesEmptyList() {
        assertTrue(todaySchedule(hours, Weekday.SUN).isEmpty())
    }

    @Test
    fun emptyHoursGiveEmptyList() {
        for (day in Weekday.entries) assertTrue(todaySchedule(emptyList(), day).isEmpty())
    }

    @Test
    fun fromSlugMapsAllSlugsAndUnknownToNull() {
        for (category in VenueCategory.entries) assertEquals(category, VenueCategory.fromSlug(category.slug))
        assertNull(VenueCategory.fromSlug("bowling-a-bilard-99"))
        assertNull(VenueCategory.fromSlug(""))
    }

    @Test
    fun fromCodeMapsAllCodesAndUnknownToNull() {
        for (day in Weekday.entries) assertEquals(day, Weekday.fromCode(day.code))
        assertNull(Weekday.fromCode("xyz"))
    }

    @Test
    fun pinColorUsesFirstCategoryInDeclarationOrderOrGrey() {
        fun venue(categories: List<VenueCategory>) =
            Venue(1, "v", "", "", 0.0, 0.0, categories, emptyList(), null, null)

        // WELLNESS is listed first but POOL is declared earlier -> POOL is the main category.
        val multi = venue(listOf(VenueCategory.WELLNESS, VenueCategory.POOL))
        assertEquals(VenueCategory.POOL, multi.primaryCategory)
        assertEquals("#1E88E5", multi.pinColorHex)
        assertNull(venue(emptyList()).primaryCategory)
        assertEquals("#757575", venue(emptyList()).pinColorHex)
    }
}
