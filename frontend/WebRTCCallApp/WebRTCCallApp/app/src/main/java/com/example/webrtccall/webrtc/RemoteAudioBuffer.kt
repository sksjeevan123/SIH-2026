package com.example.webrtccall.webrtc

import java.io.ByteArrayOutputStream

/**
 * Accumulates raw PCM16 mono audio (as delivered by AudioTrackSink.onData)
 * and hands back complete WAV-encoded chunks once enough samples have built
 * up. Mirrors the buffering logic in frontend/src/audio/AudioRecorder.js so
 * the backend sees the same shape of data regardless of which client sent it.
 */
class RemoteAudioBuffer(
    private val sampleRate: Int,
    private val chunkDurationMs: Int = 4000
) {
    private val requiredBytes = (sampleRate * chunkDurationMs / 1000) * BYTES_PER_SAMPLE
    private var buffer = ByteArrayOutputStream()

    /**
     * Feed raw PCM16 bytes in. Returns a list of complete WAV chunks that
     * became ready as a result of this call (usually 0 or 1, occasionally
     * more if a large amount of audio arrived at once).
     */
    @Synchronized
    fun addSamples(pcm16Bytes: ByteArray): List<ByteArray> {
        buffer.write(pcm16Bytes)

        val readyChunks = mutableListOf<ByteArray>()
        var current = buffer.toByteArray()

        while (current.size >= requiredBytes) {
            val chunkPcm = current.copyOfRange(0, requiredBytes)
            readyChunks.add(encodeWav(chunkPcm, sampleRate))

            current = current.copyOfRange(requiredBytes, current.size)
        }

        buffer = ByteArrayOutputStream()
        buffer.write(current)

        return readyChunks
    }

    @Synchronized
    fun reset() {
        buffer = ByteArrayOutputStream()
    }

    companion object {
        private const val BYTES_PER_SAMPLE = 2 // 16-bit PCM, mono

        fun encodeWav(pcm16Bytes: ByteArray, sampleRate: Int): ByteArray {
            val numChannels = 1
            val bitsPerSample = 16
            val byteRate = sampleRate * numChannels * bitsPerSample / 8
            val blockAlign = numChannels * bitsPerSample / 8
            val dataSize = pcm16Bytes.size

            val header = ByteArrayOutputStream(44)

            fun writeString(s: String) = header.write(s.toByteArray(Charsets.US_ASCII))
            fun writeIntLE(v: Int) {
                header.write(v and 0xff)
                header.write((v shr 8) and 0xff)
                header.write((v shr 16) and 0xff)
                header.write((v shr 24) and 0xff)
            }
            fun writeShortLE(v: Int) {
                header.write(v and 0xff)
                header.write((v shr 8) and 0xff)
            }

            writeString("RIFF")
            writeIntLE(36 + dataSize)
            writeString("WAVE")
            writeString("fmt ")
            writeIntLE(16)
            writeShortLE(1) // PCM
            writeShortLE(numChannels)
            writeIntLE(sampleRate)
            writeIntLE(byteRate)
            writeShortLE(blockAlign)
            writeShortLE(bitsPerSample)
            writeString("data")
            writeIntLE(dataSize)

            val out = ByteArrayOutputStream(44 + dataSize)
            out.write(header.toByteArray())
            out.write(pcm16Bytes)
            return out.toByteArray()
        }
    }
}