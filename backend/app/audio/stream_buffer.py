import base64
import io
import numpy as np
import soundfile as sf

class StreamBuffer:
    def __init__(self):
        self.active_buffers = {}

    def ingest_chunk(self, payload):
        call_id = payload.get("call_id")
        b64_audio = payload.get("audio")

        audio_bytes = base64.b64decode(b64_audio)
        
        with io.BytesIO(audio_bytes) as wav_io:
            data, samplerate = sf.read(wav_io, dtype='float32')

        if len(data.shape) > 1:
            data = data.mean(axis=1)

        if call_id not in self.active_buffers:
            self.active_buffers[call_id] = []
        
        self.active_buffers[call_id].append(data)
        
        continuous_audio = np.concatenate(self.active_buffers[call_id])
        return continuous_audio, samplerate

    def clear_session(self, call_id):
        if call_id in self.active_buffers:
            del self.active_buffers[call_id]