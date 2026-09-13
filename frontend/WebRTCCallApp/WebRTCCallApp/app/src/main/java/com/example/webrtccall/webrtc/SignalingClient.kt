package com.example.webrtccall.webrtc

import com.example.webrtccall.model.SignalMessage
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.util.concurrent.TimeUnit

interface SignalingListener {
    fun onConnected()
    fun onMessage(message: SignalMessage)
    fun onDisconnected()
    fun onError(error: Throwable)
}

/**
 * Thin WebSocket wrapper around the Node.js signaling server in /signaling-server.
 * The server does nothing clever - it just relays JSON messages between the two
 * clients that joined the same room, so this class stays intentionally simple.
 */
class SignalingClient(
    private val serverUrl: String, // e.g. ws://10.0.2.2:3000
    private val roomId: String,
    private val userId: String,
    private val listener: SignalingListener
) {
    private var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS) // keep the socket open indefinitely
        .build()

    fun connect() {
        val request = Request.Builder().url(serverUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                listener.onConnected()
                send(SignalMessage(type = "join", room = roomId, from = userId))
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                runCatching { SignalMessage.fromJson(text) }
                    .onSuccess { listener.onMessage(it) }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // Protocol is text/JSON only - nothing to do here.
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                listener.onDisconnected()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                listener.onError(t)
            }
        })
    }

    fun send(message: SignalMessage) {
        webSocket?.send(message.toJson())
    }

    fun disconnect() {
        runCatching { send(SignalMessage(type = "bye", room = roomId, from = userId)) }
        webSocket?.close(1000, "user hangup")
        client.dispatcher.executorService.shutdown()
    }
}
