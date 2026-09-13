// Minimal WebSocket signaling relay for the WebRTCCallApp Android app.
//
// It does NOT touch any audio/video/media - WebRTC handles that peer-to-peer.
// All this server does is let two clients that share a "room" id find each
// other and exchange the SDP offer/answer and ICE candidates they need to
// establish that direct connection. Media stays peer-to-peer.
//
// Run it with:
//   npm install
//   npm start

const WebSocket = require('ws');

const PORT = process.env.PORT || 3000;
const wss = new WebSocket.Server({ port: PORT });

// roomId -> Set of connected sockets (capped at 2 - this is a 1:1 calling demo)
const rooms = new Map();

function joinRoom(roomId, ws) {
  if (!rooms.has(roomId)) rooms.set(roomId, new Set());
  const room = rooms.get(roomId);

  if (room.size >= 2) {
    ws.send(JSON.stringify({ type: 'room-full', room: roomId, from: 'server' }));
    ws.close();
    return;
  }

  room.add(ws);
  ws.roomId = roomId;

  if (room.size === 2) {
    // Tell the peer that was already waiting that someone joined, so it
    // knows to start the offer.
    for (const client of room) {
      if (client !== ws) {
        client.send(JSON.stringify({ type: 'peer-joined', room: roomId, from: 'server' }));
      }
    }
  }
}

function leaveRoom(ws) {
  const room = rooms.get(ws.roomId);
  if (!room) return;
  room.delete(ws);
  for (const client of room) {
    client.send(JSON.stringify({ type: 'peer-left', room: ws.roomId, from: 'server' }));
  }
  if (room.size === 0) rooms.delete(ws.roomId);
}

wss.on('connection', (ws) => {
  ws.on('message', (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw.toString());
    } catch (e) {
      return; // ignore malformed messages
    }

    if (msg.type === 'join') {
      joinRoom(msg.room, ws);
      return;
    }

    if (msg.type === 'bye') {
      leaveRoom(ws);
      return;
    }

    // Relay offer / answer / ice straight to the other peer in the same room.
    const room = rooms.get(msg.room);
    if (!room) return;
    for (const client of room) {
      if (client !== ws && client.readyState === WebSocket.OPEN) {
        client.send(JSON.stringify(msg));
      }
    }
  });

  ws.on('close', () => leaveRoom(ws));
});

console.log(`Signaling server listening on ws://localhost:${PORT}`);