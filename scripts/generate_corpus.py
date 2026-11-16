"""Generate reproducible synthetic data; never overwrite existing files."""
import argparse
import json
from pathlib import Path


def generate(folder, count=3000):
    folder = Path(folder)
    for i in range(count):
        directory = folder / f"batch-{i // 100:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        filename = directory / f"dialect-{i:04d}.json"
        if i % 997 == 0:
            content = '{"utterances": [손상된 JSON'
        elif i % 13 == 0:
            content = json.dumps({"document": {"text": "다른 구조의 말뭉치"}}, ensure_ascii=False)
        else:
            content = json.dumps({"metadata": {"region": "합성 방언", "speaker": i},
                                  "utterances": [{"id": f"u{i}-{j}", "text": f"밥 묵었나? 합성 발화 {j}이다."} for j in range(30)]}, ensure_ascii=False)
        with filename.open("x", encoding="utf-8") as stream:
            stream.write(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--count", type=int, default=3000)
    args = parser.parse_args()
    generate(args.folder, args.count)
