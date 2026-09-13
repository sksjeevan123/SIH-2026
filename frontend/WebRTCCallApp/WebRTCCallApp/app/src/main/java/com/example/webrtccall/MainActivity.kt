package com.example.webrtccall

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import com.example.webrtccall.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.etServerUrl.setText(CallActivity.DEFAULT_SIGNALING_URL)

        binding.btnStartCall.setOnClickListener {
            val serverUrl = binding.etServerUrl.text.toString().trim()
            val roomId = binding.etRoomId.text.toString().trim().ifEmpty { "demo-room" }
            val userId = binding.etUserId.text.toString().trim()
                .ifEmpty { "user-${System.currentTimeMillis()}" }

            val intent = Intent(this, CallActivity::class.java).apply {
                putExtra(CallActivity.EXTRA_SERVER_URL, serverUrl)
                putExtra(CallActivity.EXTRA_ROOM_ID, roomId)
                putExtra(CallActivity.EXTRA_USER_ID, userId)
            }
            startActivity(intent)
        }
    }
}
