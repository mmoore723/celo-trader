#!/usr/bin/env python3
"""Render local Coach Celo lesson MP3s with a freely licensed Piper voice.

This produces generic character narration. It must never be supplied with a
sample of, or instructions to imitate, a real child or any other individual.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


LESSONS: dict[str, dict[str, str]] = {
    "v2_orb": {
        "range": "First, draw the morning map. From 9:30 to 9:45 Eastern, we do not trade. We mark the high and low from the first three five-minute candles. That is the opening range. No guessing yet. We are just drawing the two boundaries that matter.",
        "break": "A break gets attention, not an entry. After 9:45, price must close outside the opening range. A quick wick through the line does not count. The close is proof that price pushed through the boundary, but we still do not chase it.",
        "pullback": "Let price come back to the level. For a bullish setup, price revisits the broken range high. For a bearish setup, it revisits the broken range low. Patience is protection. If price never comes back, we let it go.",
        "confirm": "Enter only after proof. For a bullish trade, price must reclaim the range level, beat the prior candle, and be above V WAP. Three checks keep us out of the messy back-and-forth stuff we call chop.",
        "protect": "Protect the account when the idea is wrong. Every trade has an invalidation line. If price reaches it, the original idea did not work. Exiting by a rule is a win for discipline.",
    },
    "v2_trend": {
        "trend": "Start with a real trend. The quick trend line must be above the slower line for a call idea, or below it for a put idea. A flat or crossed chart is not a trend. It is a wait.",
        "pause": "Let the trend breathe. A healthy trend can pause or pull back. We want a controlled pause, not a collapse through the structure. We do not buy the middle of a burst.",
        "resume": "Wait for momentum to resume. The completed signal candle must close through its recent mini-range in the direction of the trend. We want the next push to show up on a finished candle, not halfway through one.",
        "confirm": "Enter with the trend, not against it. When structure, direction, and the completed signal agree, the paper model records the next available option quote. The chart gives the direction first, then the option is chosen.",
        "protect": "Risk rules protect the trend trade too. An invalidation level sits beyond the signal structure. If that structure breaks, the trend idea did not hold and the bot follows its exit rules. A trade needs an exit before it needs hope.",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--piper", default=".venv-coach-audio/bin/piper")
    parser.add_argument("--model", default="assets/coach-audio/voices/en_US-ryan-high.onnx")
    parser.add_argument("--output", default="frontend/public/audio/coach-celo")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    piper = root / args.piper
    model = root / args.model
    output = root / args.output
    if not piper.exists() or not model.exists():
        raise SystemExit("Coach audio engine/model not installed. See scripts/generate_coach_audio.py.")

    for course, steps in LESSONS.items():
        course_dir = output / course
        course_dir.mkdir(parents=True, exist_ok=True)
        for step, text in steps.items():
            target = course_dir / f"{step}.mp3"
            with tempfile.TemporaryDirectory() as tmp:
                wav = Path(tmp) / "narration.wav"
                subprocess.run([str(piper), "--model", str(model), "--output_file", str(wav)], input=text, text=True, check=True)
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "96k", str(target)], check=True)
            print(target.relative_to(root))


if __name__ == "__main__":
    main()
