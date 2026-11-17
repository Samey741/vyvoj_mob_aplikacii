package sk.sportnav.viewmodel

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import sk.sportnav.data.VenueRepository
import sk.sportnav.location.distanceMeters
import sk.sportnav.model.GeoPoint
import sk.sportnav.model.Venue
import sk.sportnav.model.VenueCategory
import java.io.FileNotFoundException

@OptIn(ExperimentalCoroutinesApi::class)
class MapViewModelTest {

    private val scheduler = TestCoroutineScheduler()
    private val dispatcher = StandardTestDispatcher(scheduler)

    private class FakeRepository(
        private val venues: List<Venue> = emptyList(),
        private val error: Throwable? = null,
    ) : VenueRepository {
        var calls = 0
        override fun loadVenues(): List<Venue> {
            calls++
            error?.let { throw it }
            return venues
        }
    }

    private val origin = GeoPoint(48.0, 17.0)

    // One degree of latitude is ~111.195 km; venues are placed due north of [origin].
    private fun venue(id: Int, northMeters: Double, vararg categories: VenueCategory) = Venue(
        id = id,
        name = "Venue $id",
        street = "",
        city = "",
        latitude = origin.latitude + northMeters / 111_195.0,
        longitude = origin.longitude,
        categories = categories.toList(),
        openingHours = emptyList(),
        phone = null,
        website = null,
    )

    private val gym = venue(1, 100.0, VenueCategory.FITNESS)
    private val pool = venue(2, 3_000.0, VenueCategory.POOL)
    private val multi = venue(3, 10_000.0, VenueCategory.YOGA, VenueCategory.CLIMBING)
    private val far = venue(4, 30_000.0, VenueCategory.FITNESS)
    private val uncategorised = venue(5, 200.0)
    private val all = listOf(gym, pool, multi, far, uncategorised)

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(repository: VenueRepository): MapViewModel {
        val vm = MapViewModel(repository, dispatcher)
        scheduler.advanceUntilIdle()
        return vm
    }

    private fun ids(vm: MapViewModel) = vm.uiState.value.visibleVenues.map { it.id }

    @Test
    fun initialStateIsEmptyUntilLoadCompletes() {
        val vm = MapViewModel(FakeRepository(all), dispatcher)
        assertEquals(MapUiState(), vm.uiState.value)
        scheduler.advanceUntilIdle()
        assertEquals(5, vm.uiState.value.visibleVenues.size)
    }

    @Test
    fun emptyFilterShowsAllVenues() {
        val vm = viewModel(FakeRepository(all))
        assertEquals(listOf(1, 2, 3, 4, 5), ids(vm))
        assertFalse(vm.uiState.value.loadError)
    }

    @Test
    fun categoryFilterKeepsVenuesWithAtLeastOneMatchingCategory() {
        val vm = viewModel(FakeRepository(all))
        vm.updateFilter(FilterState(categories = setOf(VenueCategory.FITNESS)))
        assertEquals(listOf(1, 4), ids(vm))

        vm.updateFilter(FilterState(categories = setOf(VenueCategory.CLIMBING)))
        assertEquals(listOf(3), ids(vm))

        vm.updateFilter(FilterState(categories = setOf(VenueCategory.POOL, VenueCategory.YOGA)))
        assertEquals(listOf(2, 3), ids(vm))
    }

    @Test
    fun distanceFilterAppliesWithLocation() {
        val vm = viewModel(FakeRepository(all))
        vm.updateUserLocation(origin)
        // Default 5 km.
        assertEquals(listOf(1, 2, 5), ids(vm))

        vm.updateFilter(FilterState(maxDistanceKm = 20.0))
        assertEquals(listOf(1, 2, 3, 5), ids(vm))
    }

    @Test
    fun distanceFilterBoundaryAtHalfKilometre() {
        val inside = venue(10, 499.0)
        val outside = venue(11, 501.0)
        val vm = viewModel(FakeRepository(listOf(inside, outside)))
        vm.updateUserLocation(origin)
        vm.updateFilter(FilterState(maxDistanceKm = 0.5))
        assertEquals(listOf(10), ids(vm))
    }

    @Test
    fun distanceFilterBoundaryAtTwentyKilometres() {
        val inside = venue(10, 19_990.0)
        val outside = venue(11, 20_010.0)
        val vm = viewModel(FakeRepository(listOf(inside, outside)))
        vm.updateUserLocation(origin)
        vm.updateFilter(FilterState(maxDistanceKm = 20.0))
        assertEquals(listOf(10), ids(vm))
    }

    /**
     * Finds a venue (due north of [origin]) and a limit in km such that the computed Haversine distance
     * equals `km * 1000.0` bit for bit, i.e. the venue sits exactly on the limit the view model compares with.
     */
    private fun venueExactlyAtLimit(id: Int, approxKm: Double): Pair<Venue, Double> {
        var lat = origin.latitude + approxKm * 1000.0 / 111_195.0
        repeat(10_000) {
            val d = distanceMeters(origin, GeoPoint(lat, origin.longitude))
            val km = d / 1000.0
            if (km * 1000.0 == d) {
                val v = venue(id, 0.0).copy(latitude = lat)
                return v to km
            }
            lat = Math.nextUp(lat)
        }
        error("no venue exactly at the limit found")
    }

    @Test
    fun venueExactlyAtHalfKilometreLimitIsIncluded() {
        val (onLimit, km) = venueExactlyAtLimit(10, 0.5)
        assertEquals(km * 1000.0, distanceMeters(origin, GeoPoint(onLimit.latitude, onLimit.longitude)), 0.0)
        assertEquals(0.5, km, 1e-3)
        val vm = viewModel(FakeRepository(listOf(onLimit)))
        vm.updateUserLocation(origin)
        vm.updateFilter(FilterState(maxDistanceKm = km))
        assertEquals(listOf(10), ids(vm))
    }

    @Test
    fun venueExactlyAtTwentyKilometreLimitIsIncluded() {
        val (onLimit, km) = venueExactlyAtLimit(10, 20.0)
        assertEquals(km * 1000.0, distanceMeters(origin, GeoPoint(onLimit.latitude, onLimit.longitude)), 0.0)
        assertEquals(20.0, km, 1e-2)
        val vm = viewModel(FakeRepository(listOf(onLimit)))
        vm.updateUserLocation(origin)
        vm.updateFilter(FilterState(maxDistanceKm = km))
        assertEquals(listOf(10), ids(vm))
    }

    @Test
    fun venueExactlyAtLimitIsIncludedWhenLocationArrivesAfterFilter() {
        val (onLimit, km) = venueExactlyAtLimit(10, 5.0)
        val vm = viewModel(FakeRepository(listOf(onLimit)))
        vm.updateFilter(FilterState(maxDistanceKm = km))
        vm.updateUserLocation(origin)
        assertEquals(listOf(10), ids(vm))
    }

    @Test
    fun venueAtExactlyZeroDistanceIsIncluded() {
        val here = venue(10, 0.0)
        val vm = viewModel(FakeRepository(listOf(here)))
        vm.updateUserLocation(origin)
        vm.updateFilter(FilterState(maxDistanceKm = 0.5))
        assertEquals(listOf(10), ids(vm))
        assertEquals(0.0, vm.distanceTo(here)!!, 1e-6)
    }

    @Test
    fun categoryAndDistanceFiltersCombine() {
        val vm = viewModel(FakeRepository(all))
        vm.updateUserLocation(origin)
        vm.updateFilter(FilterState(categories = setOf(VenueCategory.FITNESS), maxDistanceKm = 5.0))
        assertEquals(listOf(1), ids(vm))
    }

    @Test
    fun withoutLocationDistanceFilterIsOffAndDistanceToIsNull() {
        val vm = viewModel(FakeRepository(all))
        vm.updateFilter(FilterState(maxDistanceKm = 0.5))
        assertEquals(listOf(1, 2, 3, 4, 5), ids(vm))
        assertNull(vm.distanceTo(gym))

        vm.updateUserLocation(origin)
        assertEquals(listOf(1, 5), ids(vm))
        assertEquals(distanceMeters(origin, GeoPoint(gym.latitude, gym.longitude)), vm.distanceTo(gym)!!, 1e-6)

        vm.updateUserLocation(null)
        assertEquals(listOf(1, 2, 3, 4, 5), ids(vm))
        assertNull(vm.distanceTo(gym))
        assertNull(vm.uiState.value.userLocation)
    }

    @Test
    fun selectAndClearSelection() {
        val vm = viewModel(FakeRepository(all))
        assertNull(vm.uiState.value.selectedVenue)

        vm.selectVenue(2)
        assertEquals(pool, vm.uiState.value.selectedVenue)

        vm.selectVenue(null)
        assertNull(vm.uiState.value.selectedVenue)

        vm.selectVenue(999)
        assertNull(vm.uiState.value.selectedVenue)
    }

    @Test
    fun selectingHiddenVenueClearsSelection() {
        val vm = viewModel(FakeRepository(all))
        vm.updateFilter(FilterState(categories = setOf(VenueCategory.FITNESS)))
        vm.selectVenue(2) // pool is hidden by the category filter
        assertNull(vm.uiState.value.selectedVenue)

        vm.updateFilter(FilterState())
        // The rejected selection is not remembered.
        assertNull(vm.uiState.value.selectedVenue)

        vm.updateUserLocation(origin)
        vm.updateFilter(FilterState(maxDistanceKm = 0.5))
        vm.selectVenue(4) // far is hidden by the distance filter
        assertNull(vm.uiState.value.selectedVenue)
    }

    @Test
    fun filterChangeHidingSelectedVenueClearsSelection() {
        val vm = viewModel(FakeRepository(all))
        vm.selectVenue(2)
        assertEquals(pool, vm.uiState.value.selectedVenue)

        vm.updateFilter(FilterState(categories = setOf(VenueCategory.FITNESS)))
        assertEquals(listOf(1, 4), ids(vm))
        assertNull(vm.uiState.value.selectedVenue)

        // Showing the venue again does not bring the selection back.
        vm.updateFilter(FilterState())
        assertNull(vm.uiState.value.selectedVenue)
    }

    @Test
    fun filterChangeKeepingSelectedVenueKeepsSelection() {
        val vm = viewModel(FakeRepository(all))
        vm.selectVenue(2)
        vm.updateFilter(FilterState(categories = setOf(VenueCategory.POOL, VenueCategory.FITNESS)))
        assertEquals(pool, vm.uiState.value.selectedVenue)
    }

    @Test
    fun locationChangeHidingSelectedVenueClearsSelection() {
        val vm = viewModel(FakeRepository(all))
        vm.updateUserLocation(origin)
        vm.selectVenue(2) // 3 km away, inside the default 5 km
        assertEquals(pool, vm.uiState.value.selectedVenue)

        // Move the user ~20 km further north: pool is now far outside 5 km.
        vm.updateUserLocation(GeoPoint(origin.latitude + 20_000.0 / 111_195.0, origin.longitude))
        assertFalse(2 in ids(vm))
        assertNull(vm.uiState.value.selectedVenue)
    }

    @Test
    fun filterAndLocationAreReflectedInState() {
        val vm = viewModel(FakeRepository(all))
        val filter = FilterState(categories = setOf(VenueCategory.POOL), maxDistanceKm = 7.5)
        vm.updateFilter(filter)
        vm.updateUserLocation(origin)
        assertEquals(filter, vm.uiState.value.filter)
        assertEquals(origin, vm.uiState.value.userLocation)
    }

    @Test
    fun repositoryExceptionSetsLoadErrorWithoutCrashing() {
        val vm = viewModel(FakeRepository(error = FileNotFoundException("missing")))
        assertTrue(vm.uiState.value.loadError)
        assertTrue(vm.uiState.value.visibleVenues.isEmpty())

        // The view model stays usable.
        val filter = FilterState(maxDistanceKm = 10.0)
        vm.updateFilter(filter)
        vm.selectVenue(1)
        assertTrue(vm.uiState.value.loadError)
        assertEquals(filter, vm.uiState.value.filter)
    }

    @Test
    fun venuesAreLoadedExactlyOnce() {
        val repository = FakeRepository(all)
        val vm = viewModel(repository)
        vm.updateFilter(FilterState(maxDistanceKm = 1.0))
        vm.updateUserLocation(origin)
        vm.selectVenue(1)
        scheduler.advanceUntilIdle()
        assertEquals(1, repository.calls)
    }
}
