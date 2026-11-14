package shop.corgi.client.ui.home

import kotlin.math.PI
import kotlin.math.sin

/**
 * v1.9.3: the turning globe of the main screen. The meridians of a turning sphere, seen from the front, are
 * half-ellipses whose width changes as they pass from the left edge to the right one.
 */
object GlobeMotion {
    const val MERIDIANS = 4

    /**
     * Where the visible meridians are at [turn] (0..1 — one full turn): for each, its horizontal half-axis as a share
     * of the radius, from -1 (the left edge) to 1 (the right edge). They are evenly spaced and move left to right.
     */
    fun meridians(turn: Float): List<Float> = (0 until MERIDIANS).map { k ->
        val phase = ((turn + k.toFloat() / MERIDIANS) % 1f + 1f) % 1f
        sin((phase - 0.5f) * PI).toFloat()
    }
}
