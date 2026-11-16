package sk.sportnav.data

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream

class BundledDatabaseTest {

    @get:Rule
    val folder = TemporaryFolder()

    private lateinit var dir: File
    private lateinit var target: File
    private lateinit var versionFile: File
    private var opened = 0

    @Before
    fun setUp() {
        dir = folder.newFolder("databases")
        target = File(dir, "venues.sqlite")
        versionFile = File(dir, "venues.sqlite.version")
    }

    private fun bundled(content: ByteArray) = BundledDatabase(target, versionFile) {
        opened++
        ByteArrayInputStream(content)
    }

    @Test
    fun firstInstallCopiesDatabaseAndWritesVersion() {
        val result = bundled("v1".toByteArray()).install(1)

        assertEquals(target, result)
        assertArrayEquals("v1".toByteArray(), target.readBytes())
        assertEquals("1", versionFile.readText().trim())
        assertEquals(1, opened)
    }

    @Test
    fun createsMissingParentDirectory() {
        val nested = File(dir, "nested/deeper")
        val db = BundledDatabase(File(nested, "venues.sqlite"), File(nested, "venues.sqlite.version")) {
            ByteArrayInputStream("x".toByteArray())
        }
        assertTrue(db.install(1).isFile)
    }

    @Test
    fun secondInstallWithSameVersionDoesNotCopyOrOpenSource() {
        bundled("v1".toByteArray()).install(1)
        opened = 0

        bundled("changed".toByteArray()).install(1)

        assertEquals(0, opened)
        assertArrayEquals("v1".toByteArray(), target.readBytes())
    }

    @Test
    fun differentVersionCopiesAgain() {
        bundled("v1".toByteArray()).install(1)

        bundled("v2".toByteArray()).install(2)

        assertArrayEquals("v2".toByteArray(), target.readBytes())
        assertEquals("2", versionFile.readText().trim())
    }

    @Test
    fun missingDatabaseIsCopiedEvenWhenVersionMatches() {
        bundled("v1".toByteArray()).install(1)
        assertTrue(target.delete())

        bundled("v1".toByteArray()).install(1)

        assertTrue(target.isFile)
    }

    @Test
    fun failedCopyLeavesNoDatabaseOnTargetPath() {
        val failing = BundledDatabase(target, versionFile) { FailingStream() }

        try {
            failing.install(1)
            fail("expected IOException")
        } catch (_: IOException) {
        }

        assertFalse(target.exists())
        assertFalse(versionFile.exists())
        assertTrue("no temp files left", dir.listFiles().isNullOrEmpty())
    }

    @Test
    fun failedUpdateKeepsPreviousDatabase() {
        bundled("v1".toByteArray()).install(1)

        try {
            BundledDatabase(target, versionFile) { FailingStream() }.install(2)
            fail("expected IOException")
        } catch (_: IOException) {
        }

        assertArrayEquals("v1".toByteArray(), target.readBytes())
        assertEquals("1", versionFile.readText().trim())
        assertEquals(setOf("venues.sqlite", "venues.sqlite.version"), dir.list()!!.toSet())
    }

    @Test
    fun failingToOpenSourceThrowsAndLeavesNothing() {
        val missing = BundledDatabase(target, versionFile) { throw java.io.FileNotFoundException("no asset") }

        try {
            missing.install(1)
            fail("expected IOException")
        } catch (_: IOException) {
        }

        assertFalse(target.exists())
        assertTrue(dir.listFiles().isNullOrEmpty())
    }

    @Test
    fun staleTempFilesFromInterruptedAttemptsDoNotSurviveSuccessfulInstall() {
        // Simulate a process killed mid-copy: partial temp files left next to the target.
        File(dir, "venues.sqlite.tmp").writeText("partial copy from a killed process")
        File(dir, "venues.sqlite.version.tmp").writeText("partial")

        bundled("v1".toByteArray()).install(1)

        assertArrayEquals("v1".toByteArray(), target.readBytes())
        assertEquals(setOf("venues.sqlite", "venues.sqlite.version"), dir.list()!!.toSet())
    }

    @Test
    fun repeatedInterruptedAttemptsDoNotAccumulateTempFiles() {
        // A killed process cannot clean up; emulate it by leaving the temp file behind after each failure.
        repeat(3) {
            try {
                BundledDatabase(target, versionFile) { FailingStream() }.install(1)
                fail("expected IOException")
            } catch (_: IOException) {
            }
            File(dir, "venues.sqlite.tmp").writeText("partial")
        }

        bundled("v1".toByteArray()).install(1)

        assertEquals(setOf("venues.sqlite", "venues.sqlite.version"), dir.list()!!.toSet())
    }

    /** Delivers some bytes and then fails, like an interrupted copy. */
    private class FailingStream : InputStream() {
        private var served = 0
        override fun read(): Int {
            if (served++ < 10) return 0x41
            throw IOException("disk error")
        }
    }
}
