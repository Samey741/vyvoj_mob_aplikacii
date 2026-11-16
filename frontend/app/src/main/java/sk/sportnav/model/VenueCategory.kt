package sk.sportnav.model

/** Declaration order decides the venue's main category (DESIGN.md 8.13). */
enum class VenueCategory(val slug: String, val colorHex: String) {
    FITNESS("posilovny-a-silove-treninky-5", "#E53935"),
    POOL("bazeny-a-vodni-sporty-1", "#1E88E5"),
    YOGA("joga-a-zdravotni-cviceni-3", "#8E24AA"),
    CLIMBING("lezecke-steny-4", "#6D4C41"),
    RACKET("raketove-a-micove-sporty-7", "#43A047"),
    GROUP("skupinove-a-tanecni-lekce-9", "#FB8C00"),
    WELLNESS("wellness-a-relax-10", "#00ACC1");

    companion object {
        /** Pin colour of a venue without any known category (DESIGN.md 8.13). */
        const val UNKNOWN_COLOR_HEX = "#757575"

        /** Unknown slug -> null. */
        fun fromSlug(slug: String): VenueCategory? = entries.firstOrNull { it.slug == slug }
    }
}

/** Main category = first category in [VenueCategory] declaration order (DESIGN.md 8.13). */
val Venue.primaryCategory: VenueCategory?
    get() = categories.minByOrNull { it.ordinal }

/** Pin colour = `colorHex` of the main category, grey when the venue has no known category (DESIGN.md 8.13). */
val Venue.pinColorHex: String
    get() = primaryCategory?.colorHex ?: VenueCategory.UNKNOWN_COLOR_HEX
