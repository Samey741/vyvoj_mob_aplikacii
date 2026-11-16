package sk.sportnav.data

import android.database.sqlite.SQLiteException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import sk.sportnav.model.DaySchedule
import sk.sportnav.model.Venue
import sk.sportnav.model.VenueCategory
import sk.sportnav.model.Weekday
import java.io.File
import java.io.FileNotFoundException

@RunWith(RobolectricTestRunner::class)
class SQLiteVenueRepositoryTest {

    @get:Rule
    val folder = TemporaryFolder()

    private lateinit var dbFile: File
    private lateinit var venues: List<Venue>

    @Before
    fun setUp() {
        dbFile = folder.newFile("venues.sqlite")
        val stream = javaClass.classLoader!!.getResourceAsStream("test_venues.sqlite")
        assertNotNull("test_venues.sqlite fixture missing", stream)
        stream!!.use { input -> dbFile.outputStream().use { input.copyTo(it) } }
        venues = SQLiteVenueRepository { dbFile }.loadVenues()
    }

    private fun venue(id: Int): Venue = venues.single { it.id == id }

    @Test
    fun loadsAllVenuesWithGpsAndSkipsPending() {
        assertEquals(listOf(1, 2, 3, 4, 5, 6, 8, 9, 10), venues.map { it.id })
        assertTrue(venues.none { it.id == 7 })   // gps_pending = 1
    }

    @Test
    fun mapsBasicColumns() {
        val legion = venue(1)
        assertEquals("Legion Gym", legion.name)
        assertEquals("Husova 100", legion.street)
        assertEquals("Jaroměř", legion.city)
        assertEquals(50.3563, legion.latitude, 1e-9)
        assertEquals(15.9223, legion.longitude, 1e-9)
        assertEquals("+420 606 182 647", legion.phone)
        assertEquals("http://legiongym.cz/", legion.website)
        assertNull(venue(3).phone)
        assertNull(venue(3).website)
    }

    @Test
    fun mapsCategories() {
        assertEquals(listOf(VenueCategory.FITNESS), venue(1).categories)
        assertEquals(listOf(VenueCategory.POOL, VenueCategory.WELLNESS), venue(2).categories)
        assertEquals(listOf(VenueCategory.RACKET, VenueCategory.GROUP), venue(5).categories)
    }

    @Test
    fun unknownCategoryOnlyGivesEmptyCategories() {
        assertEquals("Bowling Klub Neznámy", venue(8).name)
        assertTrue(venue(8).categories.isEmpty())
    }

    @Test
    fun knownPlusUnknownCategoryKeepsOnlyKnown() {
        assertEquals(listOf(VenueCategory.FITNESS), venue(9).categories)
    }

    @Test
    fun mapsOpeningHoursIncludingClosesBeforeOpens() {
        assertEquals(
            listOf(
                DaySchedule(Weekday.MON, "06:00", "22:00"),
                DaySchedule(Weekday.TUE, "06:00", "22:00"),
                DaySchedule(Weekday.WED, "06:00", "22:00"),
                DaySchedule(Weekday.THU, "06:00", "22:00"),
                DaySchedule(Weekday.FRI, "06:00", "22:00"),
                DaySchedule(Weekday.SAT, "08:00", "20:00"),
            ),
            venue(1).openingHours,
        )
        assertTrue(DaySchedule(Weekday.FRI, "06:00", "02:00") in venue(2).openingHours)
        assertEquals(
            listOf(
                DaySchedule(Weekday.MON, "07:00", "12:00"),
                DaySchedule(Weekday.MON, "14:00", "21:00"),
                DaySchedule(Weekday.TUE, "07:00", "21:00"),
            ),
            venue(5).openingHours,
        )
        assertTrue(venue(3).openingHours.isEmpty())
    }

    @Test
    fun nullStreetAndCityMapToEmptyStrings() {
        val noAddress = venue(10)
        assertEquals("", noAddress.street)
        assertEquals("", noAddress.city)
        assertEquals(listOf(VenueCategory.WELLNESS), noAddress.categories)
    }

    @Test(expected = FileNotFoundException::class)
    fun missingFileThrows() {
        SQLiteVenueRepository { File(folder.root, "does-not-exist.sqlite") }.loadVenues()
    }

    @Test(expected = SQLiteException::class)
    fun corruptFileThrows() {
        val corrupt = folder.newFile("corrupt.sqlite")
        corrupt.writeText("this is definitely not an sqlite database, just some text ".repeat(100))
        SQLiteVenueRepository { corrupt }.loadVenues()
    }
}
