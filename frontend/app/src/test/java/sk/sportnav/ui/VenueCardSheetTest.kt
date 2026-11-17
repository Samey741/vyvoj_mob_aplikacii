package sk.sportnav.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import sk.sportnav.model.DaySchedule
import sk.sportnav.model.Weekday
import java.time.DayOfWeek
import java.util.Locale

class VenueCardSheetTest {

    private val hours = listOf(
        DaySchedule(Weekday.MON, "16:00", "22:00"),
        DaySchedule(Weekday.MON, "08:00", "12:00"),
        DaySchedule(Weekday.FRI, "22:00", "02:00"),
        DaySchedule(Weekday.SAT, "00:00", "23:59"),
    )

    @Test
    fun todayHoursListsBlocksOrderedByOpeningTime() {
        assertEquals("08:00–12:00, 16:00–22:00", formatTodayHours(hours, Weekday.MON))
    }

    @Test
    fun overnightBlockIsShownUnchanged() {
        assertEquals("22:00–02:00", formatTodayHours(hours, Weekday.FRI))
    }

    @Test
    fun dayWithoutRowsOrWithoutHoursIsNull() {
        assertNull(formatTodayHours(hours, Weekday.TUE))
        assertNull(formatTodayHours(emptyList(), Weekday.MON))
    }

    @Test
    fun javaTimeDayOfWeekMapsToWeekday() {
        assertEquals(Weekday.MON, DayOfWeek.MONDAY.toWeekday())
        assertEquals(Weekday.WED, DayOfWeek.WEDNESDAY.toWeekday())
        assertEquals(Weekday.SUN, DayOfWeek.SUNDAY.toWeekday())
        DayOfWeek.entries.forEach { assertEquals(it.name.take(3), it.toWeekday().name) }
    }

    @Test
    fun distanceBelowOneKilometreIsInRoundedMetres() {
        assertEquals("850 m", formatDistance(848.0, Locale.US))
        assertEquals("0 m", formatDistance(2.0, Locale.US))
        assertEquals("990 m", formatDistance(994.0, Locale.US))
    }

    @Test
    fun distanceNearOneKilometreNeverShows1000Metres() {
        assertEquals("1.0 km", formatDistance(996.0, Locale.US))
    }

    @Test
    fun distanceFromOneKilometreIsInKilometresWithLocaleSeparator() {
        assertEquals("1.2 km", formatDistance(1234.0, Locale.US))
        assertEquals("1,2 km", formatDistance(1234.0, Locale.forLanguageTag("sk")))
        assertEquals("12.0 km", formatDistance(12000.0, Locale.US))
    }
}
