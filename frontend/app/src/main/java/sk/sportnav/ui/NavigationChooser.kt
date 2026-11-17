package sk.sportnav.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import sk.sportnav.R
import sk.sportnav.model.GeoPoint
import sk.sportnav.navigation.MapApp
import sk.sportnav.navigation.NavigationService
import sk.sportnav.navigation.NavigationTarget
import sk.sportnav.navigation.PackageManagerAppAvailability

@StringRes
private fun MapApp.labelRes(): Int = when (this) {
    MapApp.GOOGLE_MAPS -> R.string.nav_google_maps
    MapApp.WAZE -> R.string.nav_waze
    MapApp.OTHER_GEO -> R.string.nav_other
}

/** Dialog listing the available map apps (shown only when there is more than one, DESIGN.md 5.4 item 4). */
@Composable
fun NavigationChooser(
    apps: List<MapApp>,
    onSelect: (MapApp) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.nav_choose_title)) },
        text = {
            Column {
                apps.forEach { app ->
                    Text(
                        text = stringResource(app.labelRes()),
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelect(app) }
                            .padding(vertical = 14.dp),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_close)) }
        },
    )
}

/**
 * "Navigate" flow (DESIGN.md 5.4): no map app -> message; one -> opens it directly; several ->
 * [onChoose] with the list so the UI can show [NavigationChooser]. Returns nothing, never throws.
 */
fun startNavigation(
    context: Context,
    service: NavigationService,
    appsAvailability: PackageManagerAppAvailability,
    point: GeoPoint,
    label: String,
    onChoose: (List<MapApp>) -> Unit,
) {
    val apps = service.availableApps(appsAvailability)
    when (apps.size) {
        0 -> showNoMapApp(context)
        1 -> launchNavigation(context, service.target(apps.first(), point, label))
        else -> onChoose(apps)
    }
}

/** Starts the intent; `ActivityNotFoundException` (e.g. a disabled Google Maps) -> same message as "no app" (item 5). */
fun launchNavigation(context: Context, target: NavigationTarget) {
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(target.uri)).apply {
        target.packageName?.let { setPackage(it) }
    }
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
        showNoMapApp(context)
    } catch (_: SecurityException) {
        showNoMapApp(context)
    }
}

private fun showNoMapApp(context: Context) {
    Toast.makeText(context, R.string.nav_no_app, Toast.LENGTH_LONG).show()
}
