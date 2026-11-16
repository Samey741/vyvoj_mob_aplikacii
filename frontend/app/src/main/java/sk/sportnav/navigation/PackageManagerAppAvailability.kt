package sk.sportnav.navigation

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build

/**
 * [AppAvailability] over [PackageManager]. On Android 11+ it only sees the packages and intents
 * declared in the manifest `<queries>` element (DESIGN.md 4.3, added in the UI step).
 */
class PackageManagerAppAvailability(private val packageManager: PackageManager) : AppAvailability {

    override fun isInstalled(packageName: String): Boolean = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.getPackageInfo(packageName, PackageManager.PackageInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(packageName, 0)
        }
        true
    } catch (_: PackageManager.NameNotFoundException) {
        false
    }

    override fun geoHandlerPackages(): Set<String> {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q="))
        // MATCH_DEFAULT_ONLY: only handlers an implicit startActivity can actually launch (CATEGORY_DEFAULT).
        val handlers = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.queryIntentActivities(
                intent,
                PackageManager.ResolveInfoFlags.of(PackageManager.MATCH_DEFAULT_ONLY.toLong()),
            )
        } else {
            @Suppress("DEPRECATION")
            packageManager.queryIntentActivities(intent, PackageManager.MATCH_DEFAULT_ONLY)
        }
        return handlers.mapNotNull { it.activityInfo?.packageName }.toSet()
    }
}
