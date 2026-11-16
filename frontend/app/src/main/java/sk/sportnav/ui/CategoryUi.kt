package sk.sportnav.ui

import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FitnessCenter
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Pool
import androidx.compose.material.icons.filled.SelfImprovement
import androidx.compose.material.icons.filled.Spa
import androidx.compose.material.icons.filled.SportsTennis
import androidx.compose.material.icons.filled.Terrain
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import sk.sportnav.R
import sk.sportnav.model.VenueCategory

/** Localised category name (DESIGN.md 6). */
@StringRes
fun VenueCategory.labelRes(): Int = when (this) {
    VenueCategory.FITNESS -> R.string.category_fitness
    VenueCategory.POOL -> R.string.category_pool
    VenueCategory.YOGA -> R.string.category_yoga
    VenueCategory.CLIMBING -> R.string.category_climbing
    VenueCategory.RACKET -> R.string.category_racket
    VenueCategory.GROUP -> R.string.category_group
    VenueCategory.WELLNESS -> R.string.category_wellness
}

fun VenueCategory.icon(): ImageVector = when (this) {
    VenueCategory.FITNESS -> Icons.Filled.FitnessCenter
    VenueCategory.POOL -> Icons.Filled.Pool
    VenueCategory.YOGA -> Icons.Filled.SelfImprovement
    VenueCategory.CLIMBING -> Icons.Filled.Terrain
    VenueCategory.RACKET -> Icons.Filled.SportsTennis
    VenueCategory.GROUP -> Icons.Filled.Groups
    VenueCategory.WELLNESS -> Icons.Filled.Spa
}

/** Pin colour of this category as a Compose colour (same value as on the map, DESIGN.md 8.13). */
fun VenueCategory.color(): Color = Color(android.graphics.Color.parseColor(colorHex))
