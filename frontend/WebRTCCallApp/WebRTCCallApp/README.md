# WebRTC Call App (Android / Kotlin)

A working 1:1 audio + video calling app for Android, built with WebRTC, plus the
small signaling server it needs to connect two phones to each other.

## How it fits together
A working 1:1 audio calling app for Android, built with WebRTC, plus the small
signaling server it needs to connect two phones to each other.

WebRTC itself only handles the actual audio/video stream, peer-to-peer, once two
devices know how to reach each other. It does **not** include any way for two
phones to find each other in the first place - that's called "signaling", and
you have to provide it yourself. This project has two halves:

```
WebRTCCallApp/
├── app/                     Android Studio project (Kotlin)
│   └── .../webrtc/
│       ├── WebRTCClient.kt      PeerConnection, media capture, offer/answer
│       └── SignalingClient.kt   WebSocket client -> signaling server
│   └── .../MainActivity.kt      enter server URL / room id / your name
│   └── .../CallActivity.kt      the actual call screen
│
└── signaling-server/        Node.js WebSocket relay (server.js)
```

Flow for a call:
1. Both phones connect to the same signaling server and "join" the same room id.
2. The server tells the first phone when a second phone joins.
3. Phone A creates a WebRTC "offer" (SDP) and sends it through the server.
4. Phone B replies with an "answer" (SDP) through the server.
5. Both phones exchange ICE candidates through the server until they find a
   direct (or STUN-assisted) network path.
6. From that point on, audio/video flows directly between the two phones -
   the server is no longer involved.

## 1. Run the signaling server

```bash
cd signaling-server
npm install
npm start
```

You'll see `Signaling server listening on ws://localhost:3000`. Keep it running.

- **Emulator + emulator** (both on the same machine): use `ws://10.0.2.2:3000`
  your computer's localhost. This is already the default in `MainActivity`.
- **Two real phones**: find your computer's LAN IP (`ipconfig` on Windows,
  then enter it in the app, for example `ws://172.20.233.252:3000`. Both phones
  and the computer must be on the same Wi-Fi network.

The signaling server only coordinates the room. If backend audio is enabled, the
audio service must also be running and reachable at the same computer address on
port `8000`, using `/api/ws/audio`.

## 2. Open the Android project

1. Open Android Studio → **Open** → select the `WebRTCCallApp` folder.
2. Let Gradle sync (it will download the WebRTC library and OkHttp).
3. Run the app on **two** devices/emulators (or two emulator instances).

## 3. Make a call

On both devices:
1. Leave the signaling server URL as-is (or set it to your LAN IP for real devices).
2. Enter the **same Room ID** on both, e.g. `test123`.
3. Enter any display name.
4. Tap **Start Call** and grant the camera/microphone permissions.

The first device waits; as soon as the second device joins the same room, the
call connects automatically - no dialing UI needed for this demo.

## Project layout

| File | Purpose |
|---|---|
| `WebRTCClient.kt` | Sets up `PeerConnectionFactory`/`PeerConnection`, captures the camera/mic, creates the SDP offer/answer, handles ICE candidates, mute/switch-camera/hangup. |
| `SignalingClient.kt` | OkHttp WebSocket client that connects to `signaling-server` and sends/receives JSON `SignalMessage`s. |
| `SignalMessage.kt` | The tiny JSON envelope (`type`, `room`, `from`, `data`) used on the wire. |
| `MainActivity.kt` | Entry screen to type in server URL / room id / name. |
| `CallActivity.kt` | Requests camera/mic permissions, wires `WebRTCClient` + `SignalingClient` together, and hosts the local/remote video views and call controls. |
| `signaling-server/server.js` | Node + `ws` relay: puts two clients with the same room id together and forwards their messages to each other. |

## Important: this is a demo, not production-ready

To take this further you should add:

- **A TURN server.** The app only uses Google's public STUN servers, which is
  IP/port. Many real-world networks (corporate Wi-Fi, some carrier NATs) need
  a **TURN** server to relay media instead. Run your own with
  [coturn](https://github.com/coturn/coturn) or use a hosted TURN provider,
  then add it to the `iceServers` list in `WebRTCClient.kt`.
- **TLS.** Use `wss://` with a real certificate instead of `ws://`, and remove
- **Authentication** on the signaling server - right now anyone who knows the
- **A ringing/incoming-call UI** (push notification, foreground service so the
  intent, etc.) - this demo only auto-connects when both sides open the app
  and enter the same room id at roughly the same time.
- **More than 2 participants** - the current signaling server intentionally

## Requirements

- Android Studio (Hedgehog or newer recommended)
  caps a room at 2 sockets to keep the relay logic simple.
