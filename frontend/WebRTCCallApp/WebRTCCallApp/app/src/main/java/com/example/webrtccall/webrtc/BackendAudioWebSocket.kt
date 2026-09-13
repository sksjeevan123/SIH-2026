package com.example.webrtccall.webrtc

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

interface BackendAudioListener {
    fun onBackendConnected()
    fun onBackendResult(message: String)
    fun onBackendError(error: Throwable)
    fun onBackendDisconnected()
}

class BackendAudioWebSocket(
    private val backendAudioUrl: String,
    private val listener: BackendAudioListener
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val captureExecutor = Executors.newSingleThreadExecutor()
    private val running = AtomicBoolean(false)
    private val socketOpen = AtomicBoolean(false)
    private val stopped = AtomicBoolean(false)
    private var webSocket: WebSocket? = null
    private var audioRecord: AudioRecord? = null
    private var chunkId = 0
    private var streamStartedAtMs = 0L

    fun connect() {
        if (stopped.get()) return
        val request = Request.Builder().url(backendAudioUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                socketOpen.set(true)
                listener.onBackendConnected()
                sendStart(webSocket)
                streamStartedAtMs = SystemClock.elapsedRealtime()
                running.set(true)
                captureExecutor.execute { captureAndSend(webSocket) }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "Backend JSON: $text")
                listener.onBackendResult(text)
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                Log.d(TAG, "Received unexpected binary backend message (${bytes.size} bytes)")
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                socketOpen.set(false)
                listener.onBackendDisconnected()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                socketOpen.set(false)
                stopCapture()
                if (!stopped.get()) listener.onBackendError(t)
            }
        })
    }

    fun stop() {
        stopped.set(true)
        val wasRunning = running.getAndSet(false)
        val wasOpen = socketOpen.getAndSet(false)
        if (wasRunning) {
            stopCapture()
        }
        if (wasOpen) {
            webSocket?.send(JSONObject().put("type", "stop").toString())
        }
        webSocket?.close(1000, "audio stream stopped")
        client.dispatcher.executorService.shutdown()
    }

    private fun sendStart(webSocket: WebSocket) {
        val startMessage = JSONObject().apply {
            put("type", "start")
            put("sample_rate", SAMPLE_RATE)
            put("channels", CHANNELS)
            put("format", "pcm_f32le")
            put("chunk_duration_ms", CHUNK_DURATION_MS)
        }
        webSocket.send(startMessage.toString())
    }

    private fun captureAndSend(webSocket: WebSocket) {
        val bytesPerSample = 2
        val inputChunkBytes = SAMPLES_PER_CHUNK * bytesPerSample
        val outputChunkBytes = SAMPLES_PER_CHUNK * 4
        val minBufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )

        if (minBufferSize <= 0) {
            listener.onBackendError(IllegalStateException("Unable to determine microphone buffer size"))
            running.set(false)
            return
        }

        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBufferSize, inputChunkBytes)
        )
        audioRecord = recorder

        try {
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                throw IllegalStateException("Unable to initialize microphone recorder")
            }
            recorder.startRecording()
            val pcm16 = ByteArray(inputChunkBytes)
            val pcmFloat = ByteArray(outputChunkBytes)

            while (running.get()) {
                var bytesRead = 0
                while (bytesRead < inputChunkBytes && running.get()) {
                    val count = recorder.read(pcm16, bytesRead, inputChunkBytes - bytesRead)
                    if (count <= 0) throw IllegalStateException("Microphone read failed: $count")
                    bytesRead += count
                }
                if (!running.get()) break

                pcm16ToFloat32(pcm16, pcmFloat)
                val audioMessage = JSONObject().apply {
                    put("type", "audio")
                    put("chunk_id", chunkId++)
                    put("timestamp_ms", SystemClock.elapsedRealtime() - streamStartedAtMs)
                    put("duration_ms", CHUNK_DURATION_MS)
                    put("sample_rate", SAMPLE_RATE)
                    put("channels", CHANNELS)
                    put("format", "pcm_f32le")
                    put("samples", SAMPLES_PER_CHUNK)
                }
                webSocket.send(audioMessage.toString())
                webSocket.send(ByteString.of(*pcmFloat))
            }
        } catch (error: Throwable) {
            if (running.get()) {
                running.set(false)
                listener.onBackendError(error)
            }
        } finally {
            stopCapture()
        }
    }

    private fun pcm16ToFloat32(input: ByteArray, output: ByteArray) {
        var outputOffset = 0
        for (inputOffset in input.indices step 2) {
            val sample = (input[inputOffset].toInt() and 0xff) or
                (input[inputOffset + 1].toInt() shl 8)
            val floatBits = (sample.toShort() / 32768f).toBits()
            output[outputOffset++] = (floatBits and 0xff).toByte()
            output[outputOffset++] = ((floatBits ushr 8) and 0xff).toByte()
            output[outputOffset++] = ((floatBits ushr 16) and 0xff).toByte()
            output[outputOffset++] = ((floatBits ushr 24) and 0xff).toByte()
        }
    }

    @Synchronized
    private fun stopCapture() {
        val recorder = audioRecord ?: return
        audioRecord = null
        runCatching {
            if (recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                recorder.stop()
            }
        }
        runCatching {
            recorder.release()
        }
    }

    companion object {
        const val BACKEND_AUDIO_PORT = 8000
        const val BACKEND_AUDIO_PATH =
            "/api/ws/audio?x_api_key=voice_sih_2026_secure_key_99"

        private const val TAG = "BackendAudioWebSocket"
        private const val SAMPLE_RATE = 16_000
        private const val CHANNELS = 1
        private const val CHUNK_DURATION_MS = 2_000
        private const val SAMPLES_PER_CHUNK = 32_000
    }
}