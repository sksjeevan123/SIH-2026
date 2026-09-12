class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();

        this.running = true;

        this.port.onmessage = (event) => {
            if (event.data?.type === "stop") {
                this.running = false;
            }
        };
    }

    process(inputs) {
        if (!this.running) {
            return false;
        }

        const input = inputs[0];

        if (!input || input.length === 0) {
            return true;
        }

        const channelCount = input.length;
        const frameCount = input[0]?.length;

        if (!frameCount) {
            return true;
        }

        let samples;

        // Already mono
        if (channelCount === 1) {
            // Copy because the AudioWorklet input buffer
            // is only valid for the current process callback.
            samples = new Float32Array(frameCount);
            samples.set(input[0]);
        }

        // Convert multi-channel audio to mono
        else {
            samples = new Float32Array(frameCount);

            for (let i = 0; i < frameCount; i++) {
                let sum = 0;

                for (let channel = 0; channel < channelCount; channel++) {
                    sum += input[channel][i];
                }

                samples[i] =
                    sum / channelCount;
            }
        }

        // Transfer ownership instead of copying
        // the audio buffer to the main thread.
        this.port.postMessage(
            samples,
            [samples.buffer]
        );

        return true;
    }
}

registerProcessor(
    "audio-processor",
    AudioProcessor
);
