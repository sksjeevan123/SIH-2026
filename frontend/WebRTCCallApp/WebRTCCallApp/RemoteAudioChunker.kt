package com.example.webrtccall.webrtc

import org.webrtc.AudioTrackSink
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors

/**
 * Attaches to a remote WebRTC AudioTrack via addSink() and buffers the raw PCM
 * samples it receives. Every [chunkDurationMs] milliseconds worth of audio,
 * it wraps what's buffered into a WAV byte array and hands it to [onWavChunk].
 *
 * AudioTrackSink.onData() is only invoked for remote audio tracks, so this
 * naturally captures the other person's voice, not your own mic.
 */
class RemoteAudioChunker(
    private val chunkDurationMs: Long = 3000L,
    private val onWavChunk: (ByteArray) -> Unit
) : AudioTrackSink {

    private val buffer = ByteArrayOutputStream()
    private var sampleRate = 0
    private var channels = 0
    private var bitsPerSample = 0
    private var chunkThresholdBytes = 0
    private val executor = Executors.newSingleThreadExecutor()

    override fun onData(
        audioData: ByteBuffer,
        bitsPerSample: Int,
        sampleRate: Int,
        numberOfChannels: Int,
        numberOfFrames: Int,
        absoluteCaptureTimestampMs: Long
    ) {
        // onData runs on WebRTC's internal audio thread - copy the bytes now,
        // do everything else on our own executor so we never block that thread.
        val bytes = ByteArray(audioData.remaining())
        audioData.get(bytes)

        executor.execute {
            if (this.sampleRate == 0) {
                this.sampleRate = sampleRate
                this.channels = numberOfChannels
                this.bitsPerSample = bitsPerSample
                chunkThresholdBytes =
                    (sampleRate * numberOfChannels * (bitsPerSample / 8) * chunkDurationMs / 1000).toInt()
            }
            buffer.write(bytes)
            if (buffer.size() >= chunkThresholdBytes) {
                emitChunk()
            }
        }
    }

    /** Sends whatever partial audio is left buffered. Call when the call ends. */
    fun flush() {
        executor.execute {
            if (buffer.size() > 0) emitChunk()
        }
    }

    fun shutdown() {
        flush()
        executor.shutdown()
    }

    private fun emitChunk() {
        val pcm = buffer.toByteArray()
        buffer.reset()
        val wav = pcmToWav(pcm, sampleRate, channels, bitsPerSample)
        onWavChunk(wav)
    }

    private fun pcmToWav(pcm: ByteArray, sampleRate: Int, channels: Int, bitsPerSample: Int): ByteArray {
        val byteRate = sampleRate * channels * bitsPerSample / 8
        val blockAlign = channels * bitsPerSample / 8
        val dataSize = pcm.size

        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray())
        header.putInt(36 + dataSize)
        header.put("WAVE".toByteArray())
        header.put("fmt ".toByteArray())
        header.putInt(16)              // PCM sub-chunk size
        header.putShort(1)             // audio format = PCM
        header.putShort(channels.toShort())
        header.putInt(sampleRate)
        header.putInt(byteRate)
        header.putShort(blockAlign.toShort())
        header.putShort(bitsPerSample.toShort())
        header.put("data".toByteArray())
        header.putInt(dataSize)

        return header.array() + pcm
    }
}