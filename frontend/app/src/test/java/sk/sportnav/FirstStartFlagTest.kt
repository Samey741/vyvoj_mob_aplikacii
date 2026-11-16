package sk.sportnav

import android.content.Context
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

@RunWith(RobolectricTestRunner::class)
class FirstStartFlagTest {

    private val context: Context = RuntimeEnvironment.getApplication()

    @Test
    fun trueOnlyOnTheFirstCall() {
        val prefs = context.getSharedPreferences("first-start-test", Context.MODE_PRIVATE)
        assertTrue(takeFirstStartFlag(prefs))
        assertFalse(takeFirstStartFlag(prefs))
        assertFalse(takeFirstStartFlag(prefs))
    }

    @Test
    fun flagSurvivesANewPreferencesInstance() {
        assertTrue(takeFirstStartFlag(context.getSharedPreferences("first-start-test-2", Context.MODE_PRIVATE)))
        // A later cold start reads the same file again.
        assertFalse(takeFirstStartFlag(context.getSharedPreferences("first-start-test-2", Context.MODE_PRIVATE)))
    }
}
