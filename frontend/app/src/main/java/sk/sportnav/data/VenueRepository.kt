package sk.sportnav.data

import android.database.sqlite.SQLiteDatabase
import sk.sportnav.model.DaySchedule
import sk.sportnav.model.Venue
import sk.sportnav.model.VenueCategory
import sk.sportnav.model.Weekday
import java.io.File
import java.io.FileNotFoundException

interface VenueRepository {
    /** Only venues with `gps_pending = 0`; throws when the database is missing or broken. */
    fun loadVenues(): List<Venue>
}

class SQLiteVenueRepository(private val databaseFile: () -> File) : VenueRepository {

    override fun loadVenues(): List<Venue> {
        val file = databaseFile()
        if (!file.isFile) throw FileNotFoundException("Database file not found: ${file.name}")
        val db = SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY)
        try {
            val categories = loadCategories(db)
            val hours = loadOpeningHours(db)
            return loadVenueRows(db, categories, hours)
        } finally {
            db.close()
        }
    }

    private fun loadCategories(db: SQLiteDatabase): Map<Int, List<VenueCategory>> {
        val result = HashMap<Int, MutableList<VenueCategory>>()
        db.rawQuery(
            "SELECT vc.venue_id, c.slug FROM venue_categories vc JOIN categories c ON c.id = vc.category_id",
            null,
        ).use { cursor ->
            while (cursor.moveToNext()) {
                // Unknown slug is skipped (DESIGN.md 8.11).
                val category = VenueCategory.fromSlug(cursor.getString(1)) ?: continue
                val list = result.getOrPut(cursor.getInt(0)) { mutableListOf() }
                if (category !in list) list.add(category)
            }
        }
        // Declaration order, so the first one is the main category (DESIGN.md 8.13).
        return result.mapValues { (_, list) -> list.sortedBy { it.ordinal } }
    }

    private fun loadOpeningHours(db: SQLiteDatabase): Map<Int, List<DaySchedule>> {
        val result = HashMap<Int, MutableList<DaySchedule>>()
        db.rawQuery("SELECT venue_id, day, opens, closes FROM opening_hours ORDER BY rowid", null).use { cursor ->
            while (cursor.moveToNext()) {
                val day = Weekday.fromCode(cursor.getString(1) ?: continue) ?: continue
                val opens = cursor.getString(2) ?: continue
                val closes = cursor.getString(3) ?: continue
                result.getOrPut(cursor.getInt(0)) { mutableListOf() }.add(DaySchedule(day, opens, closes))
            }
        }
        // By day (Mon -> Sun), then by opening time.
        return result.mapValues { (_, list) -> list.sortedWith(compareBy({ it.day.ordinal }, { it.opens })) }
    }

    private fun loadVenueRows(
        db: SQLiteDatabase,
        categories: Map<Int, List<VenueCategory>>,
        hours: Map<Int, List<DaySchedule>>,
    ): List<Venue> {
        val venues = mutableListOf<Venue>()
        db.rawQuery(
            "SELECT id, name, street, city, lat, lon, phone, website FROM venues " +
                "WHERE gps_pending = 0 AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY id",
            null,
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getInt(0)
                venues += Venue(
                    id = id,
                    name = cursor.getString(1),
                    street = cursor.getString(2) ?: "",   // NULL -> "" (DESIGN.md 8.11)
                    city = cursor.getString(3) ?: "",
                    latitude = cursor.getDouble(4),
                    longitude = cursor.getDouble(5),
                    categories = categories[id].orEmpty(),
                    openingHours = hours[id].orEmpty(),
                    phone = cursor.getString(6),
                    website = cursor.getString(7),
                )
            }
        }
        return venues
    }
}
