package sk.sportnav.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import sk.sportnav.data.VenueRepository
import sk.sportnav.location.distanceMeters
import sk.sportnav.model.GeoPoint
import sk.sportnav.model.Venue

data class MapUiState(
    val visibleVenues: List<Venue> = emptyList(),
    val filter: FilterState = FilterState(),
    val selectedVenue: Venue? = null,
    val userLocation: GeoPoint? = null,
    val loadError: Boolean = false,
)

class MapViewModel(
    private val repository: VenueRepository,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {

    /** Everything [MapUiState] is derived from. */
    private data class Inputs(
        val allVenues: List<Venue> = emptyList(),
        val filter: FilterState = FilterState(),
        val userLocation: GeoPoint? = null,
        val selectedId: Int? = null,
        val loadError: Boolean = false,
    )

    private val lock = Any()
    private var inputs = Inputs()
    private val _uiState = MutableStateFlow(MapUiState())
    val uiState: StateFlow<MapUiState> = _uiState

    // At most one load at a time: BundledDatabase.install must not run concurrently (DESIGN.md 8.12).
    private var loadJob: Job? = null

    init {
        loadVenues()
    }

    private fun loadVenues() {
        if (loadJob?.isActive == true) return
        loadJob = viewModelScope.launch {
            try {
                val venues = withContext(ioDispatcher) { repository.loadVenues() }
                reduce { it.copy(allVenues = venues, loadError = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                reduce { it.copy(allVenues = emptyList(), loadError = true) }
            }
        }
    }

    fun updateFilter(filter: FilterState) {
        reduce { it.copy(filter = filter) }
    }

    fun updateUserLocation(location: GeoPoint?) {
        reduce { it.copy(userLocation = location) }
    }

    /** Selects the venue with [id]; `null`, an unknown id or a currently hidden venue clears the selection. */
    fun selectVenue(id: Int?) {
        reduce { it.copy(selectedId = id) }
    }

    /** Distance from the user to [venue] in metres; `null` while the user location is unknown. */
    fun distanceTo(venue: Venue): Double? =
        _uiState.value.userLocation?.let { distanceMeters(it, GeoPoint(venue.latitude, venue.longitude)) }

    private fun reduce(transform: (Inputs) -> Inputs) {
        synchronized(lock) {
            var next = transform(inputs)
            val state = next.toUiState()
            // A selection that is not in the visible set is cleared (DESIGN.md 8.7), so the card never
            // outlives its pin; it is not restored when the venue becomes visible again.
            if (state.selectedVenue == null && next.selectedId != null) {
                next = next.copy(selectedId = null)
            }
            inputs = next
            _uiState.value = state
        }
    }

    private fun Inputs.toUiState(): MapUiState {
        val location = userLocation
        val maxMeters = filter.maxDistanceKm * 1000.0
        val visible = allVenues.filter { venue ->
            val categoryOk = filter.categories.isEmpty() || venue.categories.any { it in filter.categories }
            // Without a location the distance filter is off (DESIGN.md 8.7); the boundary is inclusive.
            val distanceOk = location == null ||
                distanceMeters(location, GeoPoint(venue.latitude, venue.longitude)) <= maxMeters
            categoryOk && distanceOk
        }
        return MapUiState(
            visibleVenues = visible,
            filter = filter,
            selectedVenue = selectedId?.let { id -> visible.firstOrNull { it.id == id } },
            userLocation = location,
            loadError = loadError,
        )
    }
}
