package sk.sportnav.data

import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/** Copies the bundled `venues.sqlite` from assets to [target] (DESIGN.md 8.12). Blocking; call off the main thread. */
class BundledDatabase(
    private val target: File,                  // context.getDatabasePath("venues.sqlite")
    private val versionFile: File,             // next to the DB; versionCode of the last copy
    private val source: () -> InputStream,     // context.assets.open("venues.sqlite")
) {
    /** Returns [target]; copies it first when it is missing or was copied by a different [versionCode]. */
    fun install(versionCode: Long): File {
        if (target.isFile && readInstalledVersion() == versionCode) return target

        val dir = target.absoluteFile.parentFile ?: throw IOException("Target has no parent directory")
        if (!dir.isDirectory && !dir.mkdirs() && !dir.isDirectory) throw IOException("Cannot create ${dir.name}")

        // Copy to a temp file in the same directory, then rename: no half-written DB after a crash.
        // Fixed temp name, so a leftover from an interrupted attempt is replaced instead of piling up.
        val temp = File(dir, target.name + ".tmp")
        temp.delete()
        try {
            source().use { input -> temp.outputStream().use { output -> input.copyTo(output) } }
            moveReplacing(temp, target)
            writeVersion(versionCode, dir)
        } catch (e: Throwable) {
            temp.delete()
            throw e
        }
        return target
    }

    private fun readInstalledVersion(): Long? =
        try {
            if (versionFile.isFile) versionFile.readText().trim().toLongOrNull() else null
        } catch (_: IOException) {
            null
        }

    private fun writeVersion(versionCode: Long, dir: File) {
        val temp = File(dir, versionFile.name + ".tmp")
        temp.delete()
        try {
            temp.writeText(versionCode.toString())
            moveReplacing(temp, versionFile)
        } catch (e: Throwable) {
            temp.delete()
            throw e
        }
    }

    private fun moveReplacing(from: File, to: File) {
        try {
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }
}
