package sk.sportnav.ui

import android.widget.Toast
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import sk.sportnav.R
import sk.sportnav.location.LocationService
import sk.sportnav.model.GeoPoint
import sk.sportnav.navigation.MapApp
import sk.sportnav.navigation.NavigationService
import sk.sportnav.navigation.PackageManagerAppAvailability
import sk.sportnav.viewmodel.MapViewModel

/** Home screen: map, filter button, "my location" button, venue card and filter sheets (DESIGN.md 5.1, 5.2). */
@Composable
fun MapScreen(
    viewModel: MapViewModel,
    locationService: LocationService,
    locationGranted: Boolean,
    onRequestLocationPermission: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val navigationService = remember { NavigationService() }

    var showFilter by rememberSaveable { mutableStateOf(false) }
    var recenterRequest by remember { mutableIntStateOf(0) }
    var locationResolved by remember { mutableStateOf(false) }
    // Keyed on the selection: it is reset whenever the selected venue becomes null or changes, e.g. when
    // a filter or location change hides it (DESIGN.md 8.7), so the next pin tap never shows a stale dialog.
    var chooserApps by remember(state.selectedVenue?.id) { mutableStateOf<List<MapApp>?>(null) }

    // The permission and the enabled providers are only checked when collection starts, so collect
    // while STARTED (restarts on every return to the app) and restart after a permission change
    // (DESIGN.md 8.14).
    LaunchedEffect(lifecycleOwner, locationGranted) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
            locationService.locations().collect { location ->
                viewModel.updateUserLocation(location)
                locationResolved = true
            }
        }
    }

    val density = LocalDensity.current
    val topInsetPx = WindowInsets.statusBars.getTop(density)
    val bottomInsetPx = WindowInsets.navigationBars.getBottom(density)

    Box(modifier = modifier.fillMaxSize()) {
        VenueMapView(
            venues = state.visibleVenues,
            userLocation = state.userLocation,
            locationGranted = locationGranted,
            locationResolved = locationResolved,
            recenterRequest = recenterRequest,
            topInsetPx = topInsetPx,
            bottomInsetPx = bottomInsetPx,
            onVenueClick = { viewModel.selectVenue(it) },
            modifier = Modifier.fillMaxSize(),
        )

        Box(modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(16.dp)) {
            SmallFloatingActionButton(
                onClick = { showFilter = true },
                modifier = Modifier.align(Alignment.TopEnd),
            ) {
                Icon(Icons.Filled.FilterList, contentDescription = stringResource(R.string.action_filter))
            }

            FloatingActionButton(
                onClick = {
                    when {
                        !locationGranted -> onRequestLocationPermission()
                        state.userLocation == null ->
                            Toast.makeText(context, R.string.location_unavailable, Toast.LENGTH_SHORT).show()
                        else -> recenterRequest++
                    }
                },
                modifier = Modifier.align(Alignment.BottomEnd).padding(bottom = 24.dp),
            ) {
                Icon(Icons.Filled.MyLocation, contentDescription = stringResource(R.string.action_my_location))
            }

            if (state.loadError) {
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                    modifier = Modifier.align(Alignment.Center),
                ) {
                    Text(
                        text = stringResource(R.string.load_error),
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 14.dp),
                    )
                }
            }
        }
    }

    state.selectedVenue?.let { venue ->
        VenueCardSheet(
            venue = venue,
            distanceMeters = viewModel.distanceTo(venue),
            onNavigate = {
                startNavigation(
                    context = context,
                    service = navigationService,
                    appsAvailability = PackageManagerAppAvailability(context.packageManager),
                    point = GeoPoint(venue.latitude, venue.longitude),
                    label = venue.name,
                    onChoose = { chooserApps = it },
                )
            },
            onDismiss = { viewModel.selectVenue(null) },
        )

        chooserApps?.let { apps ->
            NavigationChooser(
                apps = apps,
                onSelect = { app ->
                    chooserApps = null
                    launchNavigation(context, navigationService.target(app, GeoPoint(venue.latitude, venue.longitude), venue.name))
                },
                onDismiss = { chooserApps = null },
            )
        }
    }

    if (showFilter) {
        FilterSheet(
            filter = state.filter,
            distanceFilterActive = state.userLocation != null,
            onFilterChange = { viewModel.updateFilter(it) },
            onDismiss = { showFilter = false },
        )
    }
}
