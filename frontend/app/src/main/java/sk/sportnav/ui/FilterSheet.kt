package sk.sportnav.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import sk.sportnav.R
import sk.sportnav.model.VenueCategory
import sk.sportnav.viewmodel.FilterState
import java.util.Locale

private const val MIN_KM = 0.5f
private const val MAX_KM = 20f

/** Snaps a slider value to the 0.5 km grid (float interpolation can give e.g. 4.9999995), within 0.5..20 km. */
fun snapToHalfKm(value: Float): Double =
    (Math.round(value * 2f) / 2.0).coerceIn(MIN_KM.toDouble(), MAX_KM.toDouble())

/** Category checklist and distance slider (DESIGN.md 5.1, 8.7). Changes are applied immediately. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FilterSheet(
    filter: FilterState,
    distanceFilterActive: Boolean,
    onFilterChange: (FilterState) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(stringResource(R.string.filter_title), style = MaterialTheme.typography.headlineSmall)

            Text(
                stringResource(R.string.filter_categories),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = 12.dp),
            )
            Text(
                stringResource(R.string.filter_categories_hint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            VenueCategory.entries.forEach { category ->
                val checked = category in filter.categories
                val toggle = {
                    val next = if (checked) filter.categories - category else filter.categories + category
                    onFilterChange(filter.copy(categories = next))
                }
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { toggle() },
                ) {
                    Checkbox(checked = checked, onCheckedChange = { toggle() })
                    Icon(
                        imageVector = category.icon(),
                        contentDescription = null,
                        tint = category.color(),
                        modifier = Modifier.padding(horizontal = 8.dp).size(20.dp),
                    )
                    Text(stringResource(category.labelRes()), style = MaterialTheme.typography.bodyLarge)
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(stringResource(R.string.filter_distance), style = MaterialTheme.typography.titleMedium)
                Text(
                    stringResource(
                        R.string.filter_distance_value,
                        String.format(Locale.getDefault(), "%.1f", filter.maxDistanceKm),
                    ),
                    style = MaterialTheme.typography.titleMedium,
                )
            }
            Slider(
                value = filter.maxDistanceKm.toFloat(),
                onValueChange = { onFilterChange(filter.copy(maxDistanceKm = snapToHalfKm(it))) },
                valueRange = MIN_KM..MAX_KM,
                // 0.5 km steps: (20 - 0.5) / 0.5 - 1 intermediate positions.
                steps = 38,
                enabled = distanceFilterActive,
            )
            if (!distanceFilterActive) {
                Text(
                    stringResource(R.string.filter_distance_off),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
