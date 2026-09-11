import torch
import numpy as np

class VADFilter:
    def __init__(self):
        self.model, self.utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False
        )
        self.get_speech_timestamps = self.utils[0]

    def extract_speech_and_metrics(self, audio_array: np.ndarray, samplerate: int = 16000):
        tensor_audio = torch.from_numpy(audio_array)
        
        timestamps = self.get_speech_timestamps(
            tensor_audio, 
            self.model, 
            sampling_rate=samplerate
        )

        if not timestamps:
            return None, None

        speech_segments = []
        total_speech_samples = 0
        total_pause_samples = 0
        
        last_end = 0

        # Calculate prosody and behavioral metrics
        for i, ts in enumerate(timestamps):
            start = ts['start']
            end = ts['end']
            
            # Calculate pause duration between current and previous speech chunk
            if i > 0:
                total_pause_samples += (start - last_end)
                
            speech_segments.append(audio_array[start:end])
            total_speech_samples += (end - start)
            last_end = end
            
        # Convert samples to milliseconds
        total_speech_ms = (total_speech_samples / samplerate) * 1000
        total_pause_ms = (total_pause_samples / samplerate) * 1000
        
        # Calculate speech rhythm (Speech-to-Pause ratio)
        rhythm_ratio = total_speech_ms / (total_pause_ms + 1) # +1 to prevent division by zero

        prosody_metadata = {
            "speech_duration_ms": round(total_speech_ms, 2),
            "pause_duration_ms": round(total_pause_ms, 2),
            "rhythm_ratio": round(rhythm_ratio, 4),
            "segment_count": len(timestamps)
        }
        
        clean_audio = np.concatenate(speech_segments)
        return clean_audio, prosody_metadata