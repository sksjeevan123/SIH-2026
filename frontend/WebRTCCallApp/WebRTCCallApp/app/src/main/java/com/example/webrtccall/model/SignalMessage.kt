package com.example.webrtccall.model

import org.json.JSONObject

/**
 * Envelope used for every message exchanged with the signaling server.
 *
 * type: "join" | "offer" | "answer" | "ice" | "peer-joined" | "peer-left" | "bye" | "room-full"
 * room: the room/call id both peers agree on ahead of time
 * from: sender's user id
 * data: payload - SDP string, or a JSON-encoded ICE candidate (nullable)
 */
data class SignalMessage(
    val type: String,
    val room: String,
    val from: String,
    val data: String? = null
) {
    fun toJson(): String {
        val obj = JSONObject()
        obj.put("type", type)
        obj.put("room", room)
        obj.put("from", from)
        if (data != null) obj.put("data", data)
        return obj.toString()
    }

    companion object {
        fun fromJson(json: String): SignalMessage {
            val obj = JSONObject(json)
            return SignalMessage(
                type = obj.getString("type"),
                room = obj.optString("room", ""),
                from = obj.optString("from", ""),
                data = if (obj.has("data")) obj.getString("data") else null
            )
        }
    }
}
