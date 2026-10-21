"""Create local-only credentials once; never print the secret."""

import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    if not target.exists():
        target.write_text(
            "S3_ACCESS_KEY=frontend-student\nS3_SECRET_KEY=" + secrets.token_urlsafe(32) + "\n",
            encoding="utf-8",
        )
    for i in range(1, 5):
        (root / "storage" / f"vol{i}").mkdir(parents=True, exist_ok=True)
    print(".env ready; four storage folders ready (credentials not printed).")


if __name__ == "__main__":
    main()
