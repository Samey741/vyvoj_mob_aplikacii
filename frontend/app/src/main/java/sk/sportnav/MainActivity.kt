package sk.sportnav

import android.Manifest
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.core.content.pm.PackageInfoCompat
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import org.maplibre.android.MapLibre
import sk.sportnav.data.BundledDatabase
import sk.sportnav.data.SQLiteVenueRepository
import sk.sportnav.data.VenueRepository
import sk.sportnav.location.LocationService
import sk.sportnav.ui.MapScreen
import sk.sportnav.ui.theme.SportNavTheme
import sk.sportnav.viewmodel.MapViewModel
import java.io.File

private const val KEY_PERMISSION_ASKED = "location_permission_asked"

/** True exactly once per installation (the first call); the answer is persisted before it is returned. */
internal fun takeFirstStartFlag(prefs: SharedPreferences): Boolean {
    if (prefs.getBoolean(KEY_PERMISSION_ASKED, false)) return false
    prefs.edit().putBoolean(KEY_PERMISSION_ASKED, true).commit()
    return true
}

class MainActivity : ComponentActivity() {

    private val viewModel: MapViewModel by viewModels {
        viewModelFactory { initializer { MapViewModel(createRepository(applicationContext)) } }
    }

    private lateinit var locationService: LocationService
    private var locationGranted by mutableStateOf(false)

    // Both location permissions at once; "approximate only" is enough (DESIGN.md 8.14).
    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            locationGranted = hasLocationPermission()
            if (!locationGranted) {
                Toast.makeText(this, R.string.location_permission_denied, Toast.LENGTH_LONG).show()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        MapLibre.getInstance(applicationContext)
        enableEdgeToEdge()
        locationService = LocationService(applicationContext)
        locationGranted = hasLocationPermission()
        // Automatic request on the very first start only (DESIGN.md 4.3, 5.2). Later it is asked for only by
        // the "my location" button; otherwise a permanent denial would repeat the toast on every launch.
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        if (!locationGranted && takeFirstStartFlag(prefs)) requestLocationPermission()

        setContent {
            SportNavTheme {
                MapScreen(
                    viewModel = viewModel,
                    locationService = locationService,
                    locationGranted = locationGranted,
                    onRequestLocationPermission = ::requestLocationPermission,
                )
            }
        }
    }

    override fun onStart() {
        super.onStart()
        // The permission may have been granted in the system settings meanwhile.
        locationGranted = hasLocationPermission()
    }

    private fun requestLocationPermission() {
        permissionLauncher.launch(
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
        )
    }

    private fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private companion object {
        const val DB_NAME = "venues.sqlite"
        const val PREFS_NAME = "sportnav"

        /**
         * Bundled DB copied once per app version (DESIGN.md 8.12). Everything is resolved lazily inside
         * the repository call, which runs on Dispatchers.IO; a missing asset or DB error surfaces as
         * `loadError` in the view model.
         */
        fun createRepository(context: Context): VenueRepository {
            val target = context.getDatabasePath(DB_NAME)
            val installer = BundledDatabase(
                target = target,
                versionFile = File(target.absoluteFile.parentFile, "$DB_NAME.version"),
                source = { context.assets.open(DB_NAME) },
            )
            return SQLiteVenueRepository {
                val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
                installer.install(PackageInfoCompat.getLongVersionCode(packageInfo))
            }
        }
    }
}
