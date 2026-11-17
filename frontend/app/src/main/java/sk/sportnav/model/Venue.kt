package sk.sportnav.model

data class Venue(
    val id: Int,
    val name: String,
    val street: String,
    val city: String,
    val latitude: Double,
    val longitude: Double,
    val categories: List<VenueCategory>,
    val openingHours: List<DaySchedule>,
    val phone: String?,
    val website: String?,
)

enum class Weekday(val code: String) {
    MON("mon"), TUE("tue"), WED("wed"), THU("thu"), FRI("fri"), SAT("sat"), SUN("sun");

    companion object {
        /** Unknown code -> null. */
        fun fromCode(code: String): Weekday? = entries.firstOrNull { it.code == code }
    }
}

/**
 * One opening block that *starts* on [day]. If [closes] < [opens] the block ends after midnight
 * on the following day (DESIGN.md 8.10).
 */
data class DaySchedule(
    val day: Weekday,
    val opens: String,   // "06:00"
    val closes: String,  // "22:00"
)

data class GeoPoint(val latitude: Double, val longitude: Double)

/** Rows for [today], in the given order; `closes < opens` is left untouched (DESIGN.md 8.10). */
fun todaySchedule(hours: List<DaySchedule>, today: Weekday): List<DaySchedule> =
    hours.filter { it.day == today }
