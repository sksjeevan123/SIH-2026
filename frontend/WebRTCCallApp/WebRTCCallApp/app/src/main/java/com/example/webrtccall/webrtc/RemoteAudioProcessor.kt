package com.example.webrtccall.webrtc

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Kotlin port of frontend/src/audio/audioProcessor.js (VAD + spectral-
 * subtraction noise suppression), so the remote peer's audio gets the same
 * cleaning on Android before it's chunked into WAV and sent to the backend.
 *
 * Differences from the JS version, both deliberate:
 *  1. fftSize is computed from the real incoming sample rate instead of a
 *     fixed 512. The JS version hardcodes 512, which only fits a 20ms frame
 *     at rates up to ~25.6kHz. WebRTC's remote AudioTrackSink can deliver
 *     audio at 48kHz, where a 20ms frame is 960 samples - bigger than 512 -
 *     which would overrun the JS version's fixed-size arrays. Sizing it
 *     dynamically (next power of two >= frameSize) avoids that.
 *  2. inverseFFT() is ported to match the JS version's actual behavior
 *     exactly, including that it never uses the imaginary spectrum it
 *     conjugates - it re-runs a real-input FFT on the real part and divides
 *     by N. That's not a mathematically correct inverse FFT, but it's what
 *     audioProcessor.js does, and this is a like-for-like port so Android
 *     and web behave the same. Fix both together later if you want a
 *     technically-correct inverse FFT.
 */
class RemoteAudioProcessor(sampleRateHz: Int) {

    data class Frame(val cleanedPcm16: ByteArray, val isSpeech: Boolean)

    // ---- audio settings ----
    private val frameSize = max(1, (sampleRateHz * 0.02).roundToInt())

    private val fftSize: Int = run {
        var size = 512
        while (size < frameSize) size = size shl 1
        size
    }

    // ---- hamming window ----
    private val window = FloatArray(frameSize) { i ->
        (0.54 - 0.46 * cos(2.0 * PI * i / (frameSize - 1))).toFloat()
    }

    // ---- frame buffer ----
    private val frameBuffer = FloatArray(frameSize)
    private var frameIndex = 0

    // ---- VAD ----
    private val minSpeechFrames = 3
    private val minSilenceFrames = 5
    private var speechFrames = 0
    private var silenceFrames = 0
    private var isSpeech = false

    // ---- noise estimation ----
    private val noiseSpectrum = FloatArray(fftSize / 2 + 1)
    private var noiseEnergy = 0.00001f
    private var noiseFrames = 0
    private val maxNoiseFrames = 50

    // ---- noise suppression ----
    private val suppressionFactor = 0.15f
    private val minGain = 0.15f

    // ---- initial noise bootstrap ----
    private var bootstrapFrames = 0
    private val maxBootstrapFrames = 20

    /**
     * Feed raw little-endian PCM16 mono bytes (as delivered by
     * WebRTCListener.onRemoteAudioSamples). Returns one [Frame] per
     * completed 20ms frame; any leftover partial frame is buffered
     * internally for the next call.
     */
    fun process(pcm16Bytes: ByteArray): List<Frame> {
        val sampleCount = pcm16Bytes.size / 2
        val results = mutableListOf<Frame>()

        for (n in 0 until sampleCount) {
            val lo = pcm16Bytes[n * 2].toInt() and 0xff
            val hi = pcm16Bytes[n * 2 + 1].toInt()
            val sample = ((hi shl 8) or lo).toShort()

            frameBuffer[frameIndex] = sample / 32768f
            frameIndex++

            if (frameIndex == frameSize) {
                val cleaned = analyzeAndSuppress(frameBuffer)
                results.add(Frame(floatToPcm16(cleaned), isSpeech))
                frameIndex = 0
            }
        }

        return results
    }

    // ==========================================
    // SHORT-TIME ENERGY
    // ==========================================

    private fun calculateSTE(frame: FloatArray): Float {
        var energy = 0f
        for (v in frame) energy += v * v
        return energy / frame.size
    }

    // ==========================================
    // HAMMING WINDOW
    // ==========================================

    private fun applyHamming(frame: FloatArray): FloatArray {
        val real = FloatArray(fftSize)
        for (i in 0 until frameSize) real[i] = frame[i] * window[i]
        return real
    }

    // ==========================================
    // FFT (radix-2, real input only - see class doc)
    // ==========================================

    private fun fft(input: FloatArray): Pair<FloatArray, FloatArray> {
        val n = input.size
        val real = input.copyOf()
        val imag = FloatArray(n)

        // Bit reversal
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j xor bit
            if (i < j) {
                val tmp = real[i]
                real[i] = real[j]
                real[j] = tmp
            }
        }

        // Radix-2 FFT
        var length = 2
        while (length <= n) {
            val angle = -2.0 * PI / length
            val wReal = cos(angle).toFloat()
            val wImag = sin(angle).toFloat()
            val half = length shr 1

            var i = 0
            while (i < n) {
                var currentReal = 1f
                var currentImag = 0f

                for (k in 0 until half) {
                    val evenIndex = i + k
                    val oddIndex = i + k + half

                    val oddReal = real[oddIndex]
                    val oddImag = imag[oddIndex]

                    val tempReal = currentReal * oddReal - currentImag * oddImag
                    val tempImag = currentReal * oddImag + currentImag * oddReal

                    val evenReal = real[evenIndex]
                    val evenImag = imag[evenIndex]

                    real[evenIndex] = evenReal + tempReal
                    imag[evenIndex] = evenImag + tempImag

                    real[oddIndex] = evenReal - tempReal
                    imag[oddIndex] = evenImag - tempImag

                    val nextReal = currentReal * wReal - currentImag * wImag
                    currentImag = currentReal * wImag + currentImag * wReal
                    currentReal = nextReal
                }
                i += length
            }
            length = length shl 1
        }

        return Pair(real, imag)
    }

    // ==========================================
    // INVERSE FFT (ported as-is from audioProcessor.js - see class doc)
    // ==========================================

    private fun inverseFFT(real: FloatArray, imag: FloatArray): FloatArray {
        val n = real.size
        // The JS version conjugates imag here, then calls fft(inputReal)
        // without ever passing the conjugated imag in - so it has no actual
        // effect. Kept out entirely rather than computed-and-discarded.
        val (resultReal, _) = fft(real.copyOf())
        val output = FloatArray(n)
        for (i in 0 until n) output[i] = resultReal[i] / n
        return output
    }

    // ==========================================
    // SPECTRAL FLATNESS
    // ==========================================

    private fun calculateSpectralFlatness(real: FloatArray, imag: FloatArray): Float {
        var logSum = 0.0
        var arithmeticSum = 0.0
        val bins = fftSize / 2 + 1
        val epsilon = 1e-12

        for (i in 1 until bins) {
            val power = (real[i] * real[i] + imag[i] * imag[i] + epsilon)
            logSum += ln(power)
            arithmeticSum += power
        }

        val count = bins - 1
        val geometricMean = exp(logSum / count)
        val arithmeticMean = arithmeticSum / count

        return (geometricMean / (arithmeticMean + epsilon)).toFloat()
    }

    // ==========================================
    // MAGNITUDE
    // ==========================================

    private fun calculateMagnitude(real: FloatArray, imag: FloatArray): FloatArray {
        val bins = fftSize / 2 + 1
        val magnitude = FloatArray(bins)
        for (i in 0 until bins) {
            magnitude[i] = sqrt(real[i] * real[i] + imag[i] * imag[i])
        }
        return magnitude
    }

    // ==========================================
    // UPDATE NOISE SPECTRUM
    // ==========================================

    private fun updateNoiseSpectrum(magnitude: FloatArray, ste: Float) {
        val alpha = 0.9f
        for (i in magnitude.indices) {
            noiseSpectrum[i] = alpha * noiseSpectrum[i] + (1 - alpha) * magnitude[i]
        }
        noiseEnergy = alpha * noiseEnergy + (1 - alpha) * ste
        noiseFrames++
    }

    // ==========================================
    // VAD
    // ==========================================

    private fun updateVAD(ste: Float, flatness: Float) {
        val energyThreshold = max(0.00001f, noiseEnergy * 2.0f)
        val energySpeech = ste > energyThreshold
        val noiseLike = flatness > 0.85f
        val speechDetected = energySpeech && !noiseLike

        if (speechDetected) {
            speechFrames++
            silenceFrames = 0
            if (speechFrames >= minSpeechFrames) isSpeech = true
        } else {
            silenceFrames++
            speechFrames = 0
            if (silenceFrames >= minSilenceFrames) isSpeech = false
        }
    }

    // ==========================================
    // NOISE SUPPRESSION
    // ==========================================

    private fun suppressNoise(real: FloatArray, imag: FloatArray) {
        val bins = fftSize / 2 + 1

        for (i in 0 until bins) {
            val magnitude = sqrt(real[i] * real[i] + imag[i] * imag[i])
            val noise = noiseSpectrum[i]

            if (magnitude < 1e-8f) {
                real[i] = 0f
                imag[i] = 0f
                continue
            }

            // Spectral subtraction: remaining = signal - estimated noise
            val remaining = magnitude - suppressionFactor * noise
            var gain = remaining / magnitude
            gain = max(minGain, min(1f, gain))

            real[i] *= gain
            imag[i] *= gain

            // Mirror positive-frequency bins to negative-frequency bins.
            if (i > 0 && i < fftSize / 2) {
                val mirror = fftSize - i
                real[mirror] = real[i]
                imag[mirror] = -imag[i]
            }
        }
    }

    // ==========================================
    // ANALYZE + SUPPRESS
    // ==========================================

    private fun analyzeAndSuppress(frame: FloatArray): FloatArray {
        val ste = calculateSTE(frame)
        val windowed = applyHamming(frame)
        val (specReal, specImag) = fft(windowed)

        val flatness = calculateSpectralFlatness(specReal, specImag)
        val magnitude = calculateMagnitude(specReal, specImag)

        // Update VAD first using the current frame.
        updateVAD(ste, flatness)

        // Noise is learned only when the frame is classified as non-speech.
        if (!isSpeech && noiseFrames < maxNoiseFrames) {
            updateNoiseSpectrum(magnitude, ste)
        }

        // Bootstrap: before VAD is reliable, only very-low-energy frames
        // are accepted for the initial background estimate.
        if (noiseFrames == 0 && bootstrapFrames < maxBootstrapFrames) {
            val bootstrapThreshold = 0.0001f
            if (ste < bootstrapThreshold) {
                updateNoiseSpectrum(magnitude, ste)
                bootstrapFrames++
            }
        }

        suppressNoise(specReal, specImag)
        val reconstructed = inverseFFT(specReal, specImag)

        // Keep only the actual 20ms frame.
        val output = FloatArray(frameSize)
        for (i in 0 until frameSize) output[i] = reconstructed[i]
        return output
    }

    private fun floatToPcm16(samples: FloatArray): ByteArray {
        val out = ByteArray(samples.size * 2)
        for (i in samples.indices) {
            var s = samples[i]
            if (s > 1f) s = 1f
            if (s < -1f) s = -1f
            val pcm = if (s < 0) (s * 32768f).toInt() else (s * 32767f).toInt()
            out[i * 2] = (pcm and 0xff).toByte()
            out[i * 2 + 1] = ((pcm shr 8) and 0xff).toByte()
        }
        return out
    }
}