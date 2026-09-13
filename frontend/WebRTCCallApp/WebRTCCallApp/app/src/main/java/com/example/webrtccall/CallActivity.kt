package com.example.webrtccall

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.webrtccall.databinding.ActivityCallBinding
import com.example.webrtccall.model.SignalMessage
import com.example.webrtccall.webrtc.AudioAnalysisClient
import com.example.webrtccall.webrtc.AudioAnalysisListener
import com.example.webrtccall.webrtc.RemoteAudioBuffer
import com.example.webrtccall.webrtc.RemoteAudioProcessor
import com.example.webrtccall.webrtc.SignalingClient
import com.example.webrtccall.webrtc.SignalingListener
import com.example.webrtccall.webrtc.WebRTCClient
import com.example.webrtccall.webrtc.WebRTCListener
import org.json.JSONObject
import org.webrtc.IceCandidate
import org.webrtc.PeerConnection
import org.webrtc.SessionDescription
import org.webrtc.VideoTrack

class CallActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCallBinding
    private lateinit var webRTCClient: WebRTCClient
    private lateinit var signalingClient: SignalingClient
    private var callStartTime = 0L
    private var audioAnalysisClient: AudioAnalysisClient? = null
    private var remoteAudioBuffer: RemoteAudioBuffer? = null
    private var remoteAudioProcessor: RemoteAudioProcessor? = null

    private var micEnabled = true

    private val requiredPermissions = arrayOf(
        Manifest.permission.RECORD_AUDIO
    )

    private val recentResults = mutableListOf<Boolean>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCallBinding.inflate(layoutInflater)
        setContentView(binding.root)

        if (hasPermissions()) {
            setup()
        } else {
            ActivityCompat.requestPermissions(this, requiredPermissions, PERMISSION_REQUEST_CODE)
        }

        binding.btnMic.setOnClickListener {
            micEnabled = !micEnabled
            webRTCClient.toggleAudio(micEnabled)
            binding.btnMic.text = if (micEnabled) "Mute" else "Unmute"
        }

        binding.btnHangup.setOnClickListener {
            signalingClient.disconnect()
            webRTCClient.endCall()
            audioAnalysisClient?.disconnect()
            finish()
        }
    }

    private fun hasPermissions() = requiredPermissions.all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODE) {
            if (hasPermissions()) {
                setup()
            } else {
                finish()
            }
        }
    }

    private fun setup() {
        val serverUrl = intent.getStringExtra(EXTRA_SERVER_URL) ?: DEFAULT_SIGNALING_URL
        val roomId = intent.getStringExtra(EXTRA_ROOM_ID) ?: "demo-room"
        val userId = intent.getStringExtra(EXTRA_USER_ID) ?: "user-${System.currentTimeMillis()}"

        webRTCClient = WebRTCClient(this, null, object : WebRTCListener {
            override fun onLocalIceCandidate(candidate: IceCandidate) {
                val payload = JSONObject().apply {
                    put("sdpMid", candidate.sdpMid)
                    put("sdpMLineIndex", candidate.sdpMLineIndex)
                    put("candidate", candidate.sdp)
                }
                signalingClient.send(SignalMessage("ice", roomId, userId, payload.toString()))
            }

            override fun onLocalDescription(description: SessionDescription) {
                val type = if (description.type == SessionDescription.Type.OFFER) "offer" else "answer"
                signalingClient.send(SignalMessage(type, roomId, userId, description.description))
            }

            override fun onRemoteVideoTrack(track: VideoTrack) {
                // No video tracks needed
            }

            override fun onConnectionStateChange(state: PeerConnection.PeerConnectionState?) {
                runOnUiThread { binding.tvStatus.text = "Status: $state" }
            }

            override fun onRemoteAudioSamples(
                pcm16Bytes: ByteArray,
                sampleRateHz: Int,
                numberOfChannels: Int
            ) {
                ensureBackendPipeline(sampleRateHz)

                val cleanedFrames = remoteAudioProcessor?.process(pcm16Bytes) ?: emptyList()
                for (frame in cleanedFrames) {
                    val readyChunks = remoteAudioBuffer?.addSamples(frame.cleanedPcm16) ?: emptyList()
                    for (chunk in readyChunks) {
                        audioAnalysisClient?.sendChunk(chunk)
                    }
                }
            }
        })

        webRTCClient.initPeerConnection()
        webRTCClient.startLocalMedia(null, useVideo = false)

        signalingClient = SignalingClient(serverUrl, roomId, userId, object : SignalingListener {
            override fun onConnected() {
                runOnUiThread { binding.tvStatus.text = "Status: connected, waiting for peer..." }
            }

            override fun onMessage(message: SignalMessage) {
                when (message.type) {
                    "peer-joined" -> webRTCClient.createOffer()

                    "offer" -> {
                        val sdp = message.data ?: return
                        webRTCClient.onRemoteDescription(
                            SessionDescription(SessionDescription.Type.OFFER, sdp)
                        )
                        webRTCClient.createAnswer()
                    }

                    "answer" -> {
                        val sdp = message.data ?: return
                        webRTCClient.onRemoteDescription(
                            SessionDescription(SessionDescription.Type.ANSWER, sdp)
                        )
                    }

                    "ice" -> {
                        val json = JSONObject(message.data ?: return)
                        val candidate = IceCandidate(
                            json.getString("sdpMid"),
                            json.getInt("sdpMLineIndex"),
                            json.getString("candidate")
                        )
                        webRTCClient.addRemoteIceCandidate(candidate)
                    }

                    "peer-left" -> runOnUiThread { binding.tvStatus.text = "Status: peer left" }

                    "room-full" -> runOnUiThread {
                        binding.tvStatus.text = "Status: room already has 2 people"
                    }
                }
            }

            override fun onDisconnected() {
                runOnUiThread { binding.tvStatus.text = "Status: disconnected" }
            }

            override fun onError(error: Throwable) {
                runOnUiThread { binding.tvStatus.text = "Status: error ${error.message}" }
            }
        })
        signalingClient.connect()
    }

    private fun ensureBackendPipeline(sampleRateHz: Int) {
        if (remoteAudioProcessor != null) return

        remoteAudioProcessor = RemoteAudioProcessor(sampleRateHz)
        remoteAudioBuffer = RemoteAudioBuffer(sampleRate = sampleRateHz, chunkDurationMs = 4000)

        audioAnalysisClient = AudioAnalysisClient(
            serverUrl = "$BACKEND_WS_URL?x_api_key=$BACKEND_API_KEY",
            sampleRate = sampleRateHz,
            chunkDurationMs = 4000,
            listener = object : AudioAnalysisListener {
                override fun onConnected() {
                    runOnUiThread { binding.tvRiskScore.text = "Risk: analyzing..." }
                }

                override fun onResult(result: JSONObject) {
                    runOnUiThread { binding.tvRiskScore.text = formatRiskText(result) }
                }

                override fun onError(message: String) {
                    runOnUiThread { binding.tvRiskScore.text = "Risk: error ($message)" }
                }

                override fun onDisconnected() {
                    runOnUiThread { binding.tvRiskScore.text = "Risk: --" }
                }
            }
        )
        audioAnalysisClient?.connect()
    }

    private fun formatRiskText(result: JSONObject): String {
        if (callStartTime == 0L) {
            callStartTime = System.currentTimeMillis()
        }

        // Show "Collecting data..." for the first 4 seconds of the call
        val elapsedMs = System.currentTimeMillis() - callStartTime
        if (elapsedMs < 4000) {
            binding.tvRiskScore.setTextColor(android.graphics.Color.YELLOW)
            return "Detection: Collecting data..."
        }

        if (result.optString("status") == "filtered") {
            return "Status: Listening..."
        }

        val ml = result.optJSONObject("ml_inference") ?: return "Status: Analyzing"
        val isAi = ml.optBoolean("is_ai", false)

        recentResults.add(isAi)
        if (recentResults.size > 3) {
            recentResults.removeAt(0)
        }

        val stableIsAi = recentResults.count { it } > (recentResults.size / 2)
        val label = if (stableIsAi) "AI Generated" else "Real Human"

        if (stableIsAi) {
            binding.tvRiskScore.setTextColor(android.graphics.Color.RED)
        } else {
            binding.tvRiskScore.setTextColor(android.graphics.Color.GREEN)
        }

        return "Detection: $label"
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::webRTCClient.isInitialized) webRTCClient.endCall()
        if (::signalingClient.isInitialized) signalingClient.disconnect()
        audioAnalysisClient?.disconnect()
    }

    companion object {
        const val EXTRA_SERVER_URL = "extra_server_url"
        const val EXTRA_ROOM_ID = "extra_room_id"
        const val EXTRA_USER_ID = "extra_user_id"

        const val DEFAULT_SIGNALING_URL = "ws://192.168.137.1:3000"
        const val BACKEND_WS_URL = "ws://192.168.137.1:8000/api/ws/audio"
        const val BACKEND_API_KEY = "voice_sih_2026_secure_key_99"

        private const val PERMISSION_REQUEST_CODE = 1001
    }
}