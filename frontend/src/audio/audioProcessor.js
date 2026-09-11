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

        /*
         * input contains one Float32Array per audio channel.
         *
         * We convert everything to mono because the voice
         * detection model only needs a single speech channel.
         */

        const leftChannel = input[0];

        if (!leftChannel) {
            return true;
        }

        let samples;

        // Mono input
        if (input.length === 1) {
            samples = new Float32Array(leftChannel.length);
            samples.set(leftChannel);
        }

        // Stereo / multi-channel input
        else {
            const frameCount = leftChannel.length;

            samples = new Float32Array(frameCount);

            for (let i = 0; i < frameCount; i++) {
                let sum = 0;

                for (let channel = 0; channel < input.length; channel++) {
                    sum += input[channel]?.[i] || 0;
                }

                samples[i] = sum / input.length;
            }
        }

        /*
         * Transfer the ArrayBuffer instead of copying it again
         * when it reaches the main thread.
         */
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