package com.example.karaoke

import androidx.appcompat.app.AppCompatActivity
import android.os.Bundle
import android.widget.TextView
import com.google.android.exoplayer2.ExoPlayer
import com.google.android.exoplayer2.MediaItem
import android.net.Uri
import android.os.Handler
import android.os.Looper

class MainActivity : AppCompatActivity() {

    private lateinit var player: ExoPlayer
    private lateinit var lyricsTextView: TextView

    // Example transcript data: each segment has startTimeMs, endTimeMs, text
    private val lyricsData = listOf(
        Segment(0, 5000, "Instrumental intro..."),
        Segment(5000, 10000, "First line of lyrics"),
        Segment(10000, 15000, "Second line of lyrics")
        // Extend as needed
    )

    private val handler = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Link UI
        lyricsTextView = findViewById(R.id.lyrics_text)

        // Initialize ExoPlayer
        player = ExoPlayer.Builder(this).build()

        // Find the PlayerView from layout
        val playerView: com.google.android.exoplayer2.ui.PlayerView = findViewById(R.id.player_view)
        playerView.player = player

        // Example: load processed karaoke video from the backend
        // Replace with actual URL from the /process endpoint
        val mediaItem = MediaItem.fromUri(
            Uri.parse("http://YOUR_SERVER_URL/processed/some_video_karaoke.mp4")
        )
        player.setMediaItem(mediaItem)
        player.prepare()
        player.play()

        // Start updating lyrics
        syncLyrics()
    }

    private fun syncLyrics() {
        handler.post(object : Runnable {
            override fun run() {
                val currentPositionMs = player.currentPosition
                val currentSegment = lyricsData.find {
                    currentPositionMs >= it.startMs && currentPositionMs <= it.endMs
                }

                if (currentSegment != null) {
                    lyricsTextView.text = currentSegment.text
                } else {
                    lyricsTextView.text = ""
                }

                handler.postDelayed(this, 500)
            }
        })
    }

    override fun onDestroy() {
        super.onDestroy()
        player.release()
    }
}

data class Segment(
    val startMs: Long,
    val endMs: Long,
    val text: String
)