"""Refresh a compact, read-only Telegram eligibility explanation for GitHub Pages."""
import os
from h1lab.telegram_eligibility import publish


def main():
    return publish(".", source_commit=os.environ.get("LAB_SOURCE_SHA", "unknown"))


if __name__ == "__main__":
    main()
