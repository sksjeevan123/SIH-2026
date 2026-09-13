package com.example.webrtccall.webrtc

import okhttp3.*
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.concurrent.Executors

interface AudioAnalysisListener {
    fun onConnected()
    fun onResult(result: JSONObject)
    fun onError(message: String)
    fun onDisconnected()
}

class AudioAnalysisClient(
    private val serverUrl: String,
    private val sampleRate: Int,
    private val chunkDurationMs: Int,
    private val listener: AudioAnalysisListener
) {
    private val client = OkHttpClient()
    private var webSocket: WebSocket? = null
    private val workerExecutor = Executors.newSingleThreadExecutor()

    fun connect() {
        val request = Request.Builder().url(serverUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                listener.onConnected()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    listener.onResult(json)
                } catch (e: Exception) {
                    listener.onError("Invalid JSON: ${e.message}")
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                listener.onDisconnected()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                listener.onError(t.message ?: "Unknown network error")
            }
        })
    }

    fun sendChunk(pcmChunk: ByteArray) {
        workerExecutor.execute {
            try {
                webSocket?.send(pcmChunk.toByteString(0, pcmChunk.size))
            } catch (e: Exception) {
                // Handle send failure if needed
            }
        }
    }

    fun disconnect() {
        webSocket?.close(1000, "Client disconnect")
        workerExecutor.shutdown()
    }
}