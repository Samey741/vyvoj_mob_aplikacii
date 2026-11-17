package sk.sportnav.ui

import android.annotation.SuppressLint
import android.graphics.RectF
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import org.maplibre.android.MapLibre
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.location.LocationComponentActivationOptions
import org.maplibre.android.location.modes.CameraMode
import org.maplibre.android.location.modes.RenderMode
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.expressions.Expression
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.PropertyFactory
import org.maplibre.android.style.layers.SymbolLayer
import org.maplibre.android.style.sources.GeoJsonOptions
import org.maplibre.android.style.sources.GeoJsonSource
import org.maplibre.geojson.Feature
import org.maplibre.geojson.FeatureCollection
import org.maplibre.geojson.Point
import sk.sportnav.model.GeoPoint
import sk.sportnav.model.Venue
import sk.sportnav.model.pinColorHex

/** OpenFreeMap style; the only place the tile source is named (DESIGN.md 8.6, 12). */
const val MAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty"

private const val SOURCE_ID = "venues"
private const val CLUSTER_LAYER_ID = "venue-clusters"
private const val CLUSTER_COUNT_LAYER_ID = "venue-cluster-count"
private const val POINT_LAYER_ID = "venue-points"
private const val CLUSTER_COLOR = "#37474F"
private const val PROP_ID = "id"
private const val PROP_COLOR = "color"
private const val PROP_POINT_COUNT = "point_count"
private const val USER_ZOOM = 13.0
private const val DEFAULT_ZOOM = 6.0
private val DEFAULT_CENTER = LatLng(49.2, 17.5)

private const val MAP_EDGE_MARGIN_DP = 8
private const val MAP_LOGO_WIDTH_DP = 88 // maplibre_logo_icon is 88 x 23 dp

/** Start margin of the attribution button: just right of the MapLibre logo, so the two do not overlap. */
fun attributionStartMarginPx(density: Float): Int =
    ((MAP_EDGE_MARGIN_DP + MAP_LOGO_WIDTH_DP + MAP_EDGE_MARGIN_DP) * density).toInt()

/**
 * One GeoJSON point per venue with the properties `id` (number) and `color` (hex of the main category,
 * grey without a known category; DESIGN.md 8.6, 8.13). GeoJSON order is longitude, latitude.
 */
fun buildVenueFeatures(venues: List<Venue>): FeatureCollection =
    FeatureCollection.fromFeatures(
        venues.map { venue ->
            Feature.fromGeometry(Point.fromLngLat(venue.longitude, venue.latitude)).also {
                it.addNumberProperty(PROP_ID, venue.id)
                it.addStringProperty(PROP_COLOR, venue.pinColorHex)
            }
        },
    )

/**
 * What the camera has already done, kept across rotation (`rememberSaveable`): the last camera
 * position and the auto-centering [stage] (0 = nothing yet, 1 = fitted to all venues, 2 = centered on the user).
 */
private class CameraMemory(val raw: DoubleArray = DoubleArray(6)) {
    // raw = [hasCamera, lat, lon, zoom, bearing, stage]
    val hasCamera: Boolean get() = raw[0] != 0.0
    var stage: Int
        get() = raw[5].toInt()
        set(value) {
            raw[5] = value.toDouble()
        }

    fun store(position: CameraPosition) {
        val target = position.target ?: return
        raw[0] = 1.0
        raw[1] = target.latitude
        raw[2] = target.longitude
        raw[3] = position.zoom
        raw[4] = position.bearing
    }

    fun toPosition(): CameraPosition =
        CameraPosition.Builder().target(LatLng(raw[1], raw[2])).zoom(raw[3]).bearing(raw[4]).build()

    companion object {
        val Saver: Saver<CameraMemory, DoubleArray> = Saver(save = { it.raw.copyOf() }, restore = { CameraMemory(it) })
    }
}

/** Forwards lifecycle events to [MapView] (DESIGN.md 8.6) and never calls a method twice or out of order. */
private class MapLifecycleForwarder(private val mapView: MapView) {
    private var created = false
    private var started = false
    private var resumed = false

    fun onEvent(event: Lifecycle.Event) {
        when (event) {
            Lifecycle.Event.ON_CREATE -> if (!created) {
                created = true
                mapView.onCreate(null)
            }
            Lifecycle.Event.ON_START -> if (created && !started) {
                started = true
                mapView.onStart()
            }
            Lifecycle.Event.ON_RESUME -> if (started && !resumed) {
                resumed = true
                mapView.onResume()
            }
            Lifecycle.Event.ON_PAUSE -> pause()
            Lifecycle.Event.ON_STOP -> stop()
            Lifecycle.Event.ON_DESTROY -> destroy()
            else -> Unit
        }
    }

    private fun pause() {
        if (resumed) {
            resumed = false
            mapView.onPause()
        }
    }

    private fun stop() {
        pause()
        if (started) {
            started = false
            mapView.onStop()
        }
    }

    /** Also used when the composable leaves the composition while the activity is still alive. */
    fun destroy() {
        stop()
        if (created) {
            created = false
            mapView.onDestroy()
        }
    }
}

/**
 * MapLibre [MapView] with the venues as one clustered GeoJSON source (DESIGN.md 5.3, 8.6).
 *
 * [venues] changes only update the source data. [locationGranted] switches the blue dot (LocationComponent)
 * on; [locationResolved] tells that the location collection has produced a first value (possibly `null`),
 * so the initial camera can fall back to the area of all venues. A change of [recenterRequest]
 * (> 0) moves the camera to [userLocation].
 */
@SuppressLint("MissingPermission") // the location component is only activated when the permission is granted
@Composable
fun VenueMapView(
    venues: List<Venue>,
    userLocation: GeoPoint?,
    locationGranted: Boolean,
    locationResolved: Boolean,
    recenterRequest: Int,
    topInsetPx: Int,
    bottomInsetPx: Int,
    onVenueClick: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val density = context.resources.displayMetrics.density

    // MapLibre.getInstance must run before the first MapView is created.
    val mapView = remember {
        MapLibre.getInstance(context)
        MapView(context)
    }
    val memory = rememberSaveable(saver = CameraMemory.Saver) { CameraMemory() }
    var map by remember { mutableStateOf<MapLibreMap?>(null) }
    var style by remember { mutableStateOf<Style?>(null) }
    val currentVenues by rememberUpdatedState(venues)
    val currentUserLocation by rememberUpdatedState(userLocation)
    val currentOnVenueClick by rememberUpdatedState(onVenueClick)

    DisposableEffect(mapView, lifecycleOwner) {
        val forwarder = MapLifecycleForwarder(mapView)
        val observer = LifecycleEventObserver { _, event -> forwarder.onEvent(event) }
        // Adding the observer replays the events up to the current state (create, start, resume).
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            map = null
            style = null
            forwarder.destroy()
        }
    }

    DisposableEffect(mapView) {
        var disposed = false
        mapView.getMapAsync { mapLibreMap ->
            if (disposed) return@getMapAsync
            mapLibreMap.cameraPosition = if (memory.hasCamera) {
                memory.toPosition()
            } else {
                CameraPosition.Builder().target(DEFAULT_CENTER).zoom(DEFAULT_ZOOM).build()
            }
            mapLibreMap.addOnCameraIdleListener { memory.store(mapLibreMap.cameraPosition) }
            mapLibreMap.addOnMapClickListener { latLng ->
                val center = mapLibreMap.projection.toScreenLocation(latLng)
                val slop = 20f * density
                val area = RectF(center.x - slop, center.y - slop, center.x + slop, center.y + slop)
                val hits = mapLibreMap.queryRenderedFeatures(area, CLUSTER_LAYER_ID, POINT_LAYER_ID)
                val cluster = hits.firstOrNull { it.hasProperty(PROP_POINT_COUNT) }
                val point = hits.firstOrNull { !it.hasProperty(PROP_POINT_COUNT) }
                when {
                    // Cluster -> zoom in by 2 levels on its center.
                    cluster != null -> {
                        val geometry = cluster.geometry() as? Point
                        val target = if (geometry != null) LatLng(geometry.latitude(), geometry.longitude()) else latLng
                        mapLibreMap.animateCamera(
                            CameraUpdateFactory.newLatLngZoom(target, mapLibreMap.cameraPosition.zoom + 2.0),
                        )
                        true
                    }
                    point != null -> {
                        point.getNumberProperty(PROP_ID)?.let { currentOnVenueClick(it.toInt()) }
                        true
                    }
                    else -> false
                }
            }
            mapLibreMap.setStyle(Style.Builder().fromUri(MAP_STYLE_URL)) { loaded ->
                if (disposed) return@setStyle
                addVenueLayers(loaded)
                style = loaded
            }
            map = mapLibreMap
        }
        onDispose { disposed = true }
    }

    // Keep the attribution, logo and compass clear of the system bars and the filter button.
    LaunchedEffect(map, topInsetPx, bottomInsetPx) {
        val settings = map?.uiSettings ?: return@LaunchedEffect
        val margin = (MAP_EDGE_MARGIN_DP * density).toInt()
        // Both sit bottom-start: the logo first, the attribution "i" button to the right of it.
        settings.setLogoMargins(margin, 0, 0, bottomInsetPx + margin)
        settings.setAttributionMargins(attributionStartMarginPx(density), 0, 0, bottomInsetPx + margin)
        settings.setCompassMargins(0, topInsetPx + (72 * density).toInt(), (16 * density).toInt(), 0)
    }

    // Data updates only touch the source; the map is not recreated.
    LaunchedEffect(style, venues) {
        val loaded = style ?: return@LaunchedEffect
        loaded.getSourceAs<GeoJsonSource>(SOURCE_ID)?.setGeoJson(buildVenueFeatures(venues))
    }

    // Blue dot with the compass arrow; only with a granted permission (DESIGN.md 8.6).
    LaunchedEffect(map, style, locationGranted) {
        val mapLibreMap = map ?: return@LaunchedEffect
        val loaded = style ?: return@LaunchedEffect
        if (!locationGranted) return@LaunchedEffect
        try {
            val component = mapLibreMap.locationComponent
            component.activateLocationComponent(
                LocationComponentActivationOptions.builder(context, loaded)
                    .useDefaultLocationEngine(true)
                    .build(),
            )
            component.isLocationComponentEnabled = true
            component.cameraMode = CameraMode.NONE
            component.renderMode = RenderMode.COMPASS
        } catch (_: SecurityException) {
            // permission revoked in the meantime: no blue dot
        }
    }

    // Initial camera: the user when known, otherwise the area of all venues (DESIGN.md 5.3, 8.7).
    LaunchedEffect(map, userLocation, locationResolved, venues.isNotEmpty()) {
        val mapLibreMap = map ?: return@LaunchedEffect
        val location = userLocation
        if (location != null) {
            if (memory.stage < 2) {
                mapLibreMap.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(location.latitude, location.longitude), USER_ZOOM))
                memory.stage = 2
            }
        } else if (memory.stage == 0 && locationResolved && currentVenues.isNotEmpty()) {
            mapLibreMap.moveCamera(fitAll(currentVenues))
            memory.stage = 1
        }
    }

    // "My location" button.
    LaunchedEffect(recenterRequest) {
        if (recenterRequest <= 0) return@LaunchedEffect
        val location = currentUserLocation ?: return@LaunchedEffect
        map?.animateCamera(CameraUpdateFactory.newLatLngZoom(LatLng(location.latitude, location.longitude), USER_ZOOM))
    }

    AndroidView(factory = { mapView }, modifier = modifier)
}

private fun fitAll(venues: List<Venue>) =
    if (venues.size == 1) {
        CameraUpdateFactory.newLatLngZoom(LatLng(venues[0].latitude, venues[0].longitude), USER_ZOOM)
    } else {
        val bounds = LatLngBounds.Builder().apply { venues.forEach { include(LatLng(it.latitude, it.longitude)) } }.build()
        CameraUpdateFactory.newLatLngBounds(bounds, 120)
    }

private fun addVenueLayers(style: Style) {
    style.addSource(
        GeoJsonSource(
            SOURCE_ID,
            FeatureCollection.fromFeatures(emptyList<Feature>()),
            GeoJsonOptions().withCluster(true).withClusterRadius(50).withClusterMaxZoom(14),
        ),
    )

    val isCluster = Expression.has(PROP_POINT_COUNT)

    style.addLayer(
        CircleLayer(CLUSTER_LAYER_ID, SOURCE_ID).withFilter(isCluster).withProperties(
            PropertyFactory.circleColor(CLUSTER_COLOR),
            // Bigger circle for bigger clusters.
            PropertyFactory.circleRadius(
                Expression.step(
                    Expression.get(PROP_POINT_COUNT),
                    Expression.literal(16),
                    Expression.stop(10, 20),
                    Expression.stop(50, 24),
                ),
            ),
            PropertyFactory.circleStrokeColor("#FFFFFF"),
            PropertyFactory.circleStrokeWidth(2f),
        ),
    )

    // The count uses a font of the Liberty style; if the glyphs cannot be loaded the clusters stay
    // visible as plain circles (DESIGN.md 12).
    style.addLayer(
        SymbolLayer(CLUSTER_COUNT_LAYER_ID, SOURCE_ID).withFilter(isCluster).withProperties(
            PropertyFactory.textField(Expression.get("point_count_abbreviated")),
            PropertyFactory.textFont(arrayOf("Noto Sans Bold")),
            PropertyFactory.textSize(13f),
            PropertyFactory.textColor("#FFFFFF"),
            PropertyFactory.textAllowOverlap(true),
            PropertyFactory.textIgnorePlacement(true),
        ),
    )

    style.addLayer(
        CircleLayer(POINT_LAYER_ID, SOURCE_ID).withFilter(Expression.not(isCluster)).withProperties(
            PropertyFactory.circleColor(Expression.toColor(Expression.get(PROP_COLOR))),
            PropertyFactory.circleRadius(9f),
            PropertyFactory.circleStrokeColor("#FFFFFF"),
            PropertyFactory.circleStrokeWidth(2f),
        ),
    )
}
