import asyncio
import json
import numpy as np

from app.ml.inference import analyze_voice_authenticity


sample_rate = 16000
duration = 3

t = np.linspace(
    0,
    duration,
    sample_rate * duration,
    endpoint=False
)

audio = (
    0.3 * np.sin(2 * np.pi * 440 * t)
    + 0.1 * np.sin(2 * np.pi * 880 * t)
).astype(np.float32)


# 2D input
data = np.array([
    audio,
    np.zeros_like(audio)
], dtype=np.float32)


print("========== INPUT ==========")
print("Shape:", data.shape)
print("Dimensions:", data.ndim)
print("Dtype:", data.dtype)
print("Min:", data.min())
print("Max:", data.max())


async def main():

    result = await analyze_voice_authenticity(
        data,
        sample_rate=sample_rate
    )

    print("\n========== MODEL OUTPUT ==========")

    print("Risk Score:", result["risk_score"])
    print("Fake Probability:", result["fake_probability"])
    print("Real Probability:", result["real_probability"])
    print("Risk Level:", result["risk_level"])
    print("Is Fake:", result["is_fake"])

    print("\nAcoustic Analysis:")
    print(json.dumps(result["acoustic_analysis"], indent=4))

    print("\nReceived Parameters:")
    print("Number of parameters:", len(
        result["received_parameters"]["raw_parameters"]
    ))
    print("First 10 parameters:",
          result["received_parameters"]["raw_parameters"][:10])


if __name__ == "__main__":
    asyncio.run(main())