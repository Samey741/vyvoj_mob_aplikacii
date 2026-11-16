package sk.sportnav.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Directions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import sk.sportnav.R
import sk.sportnav.model.DaySchedule
import sk.sportnav.model.Venue
import sk.sportnav.model.Weekday
import sk.sportnav.model.todaySchedule
import java.time.DayOfWeek
import java.time.LocalDate
import java.util.Locale

/** `java.time` weekday -> [Weekday] (both start on Monday). */
fun DayOfWeek.toWeekday(): Weekday = Weekday.entries[ordinal]

/**
 * Today's opening blocks as text, e.g. `06:00–22:00, 16:00–22:00` (DESIGN.md 8.10): rows for [today]
 * ordered by opening time; `closes < opens` is shown as is. `null` when the venue has no row for [today].
 */
fun formatTodayHours(hours: List<DaySchedule>, today: Weekday): String? =
    todaySchedule(hours, today)
        .sortedBy { it.opens }
        .takeIf { it.isNotEmpty() }
        ?.joinToString(", ") { "${it.opens}–${it.closes}" }

/** `850 m` below 1 km (rounded to 10 m), otherwise `1.2 km` with the decimal separator of [locale]. */
fun formatDistance(meters: Double, locale: Locale): String {
    if (meters >= 1000.0) return String.format(locale, "%.1f km", meters / 1000.0)
    val rounded = (Math.round(meters / 10.0) * 10).toInt()
    // Rounding up must not produce "1000 m".
    return if (rounded >= 1000) String.format(locale, "%.1f km", 1.0) else "$rounded m"
}

/** Bottom sheet with the venue card (DESIGN.md 5.1, 5.3). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VenueCardSheet(
    venue: Venue,
    distanceMeters: Double?,
    onNavigate: () -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(venue.name, style = MaterialTheme.typography.headlineSmall)

            venue.categories.forEach { category ->
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(
                        imageVector = category.icon(),
                        contentDescription = null,
                        tint = category.color(),
                        modifier = Modifier.size(20.dp),
                    )
                    Text(stringResource(category.labelRes()), style = MaterialTheme.typography.bodyLarge)
                }
            }

            // NULL street / city arrive as "" and are not shown (DESIGN.md 8.11).
            val address = listOf(venue.street, venue.city).filter { it.isNotBlank() }.joinToString(", ")
            if (address.isNotEmpty()) {
                Text(address, style = MaterialTheme.typography.bodyMedium)
            }
            if (distanceMeters != null) {
                Text(formatDistance(distanceMeters, Locale.getDefault()), style = MaterialTheme.typography.bodyMedium)
            }

            val hours = formatTodayHours(venue.openingHours, LocalDate.now().dayOfWeek.toWeekday())
            Text(
                text = when {
                    hours != null -> stringResource(R.string.venue_hours_today, hours)
                    venue.openingHours.isNotEmpty() -> stringResource(R.string.venue_hours_closed_today)
                    else -> stringResource(R.string.venue_hours_unavailable)
                },
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                text = stringResource(R.string.venue_attribution),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Button(onClick = onNavigate, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
                Icon(Icons.Filled.Directions, contentDescription = null, modifier = Modifier.size(18.dp))
                Text(stringResource(R.string.venue_navigate), modifier = Modifier.padding(start = 8.dp))
            }
        }
    }
}
