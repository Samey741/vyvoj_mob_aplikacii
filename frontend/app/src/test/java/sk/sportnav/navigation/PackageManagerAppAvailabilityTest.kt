package sk.sportnav.navigation

import android.app.Application
import android.content.ComponentName
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.content.pm.ResolveInfo
import android.net.Uri
import org.robolectric.RuntimeEnvironment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf

@RunWith(RobolectricTestRunner::class)
class PackageManagerAppAvailabilityTest {

    private val app: Application = RuntimeEnvironment.getApplication()

    @Test
    fun isInstalledReflectsPackageManager() {
        val availability = PackageManagerAppAvailability(app.packageManager)
        assertTrue(availability.isInstalled(app.packageName))
        assertFalse(availability.isInstalled("com.waze"))
    }

    @Test
    fun geoHandlerPackagesListsResolvedActivities() {
        val resolve = ResolveInfo().apply {
            activityInfo = ActivityInfo().apply {
                packageName = "net.osmand"
                name = "net.osmand.MapActivity"
            }
        }
        shadowOf(app.packageManager).addResolveInfoForIntent(
            Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=")),
            resolve,
        )

        assertEquals(setOf("net.osmand"), PackageManagerAppAvailability(app.packageManager).geoHandlerPackages())
    }

    @Test
    fun noGeoHandlerGivesEmptySet() {
        assertTrue(PackageManagerAppAvailability(app.packageManager).geoHandlerPackages().isEmpty())
    }

    private fun registerGeoHandler(packageName: String, withDefaultCategory: Boolean) {
        val component = ComponentName(packageName, "$packageName.MapActivity")
        val shadow = shadowOf(app.packageManager)
        shadow.addActivityIfNotPresent(component)
        val filter = IntentFilter(Intent.ACTION_VIEW).apply {
            addDataScheme("geo")
            if (withDefaultCategory) addCategory(Intent.CATEGORY_DEFAULT)
        }
        shadow.addIntentFilterForActivity(component, filter)
    }

    @Test
    fun geoHandlerWithoutDefaultCategoryIsNotReported() {
        registerGeoHandler("net.osmand", withDefaultCategory = true)
        registerGeoHandler("com.example.nodefault", withDefaultCategory = false)

        assertEquals(setOf("net.osmand"), PackageManagerAppAvailability(app.packageManager).geoHandlerPackages())
    }
}
