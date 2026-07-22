"""Download, normalize, and persist the current official TransJakarta GTFS feed."""

import argparse
import asyncio
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.transit_writer import replace_transjakarta_dataset
from app.ingestion.gtfs.transjakarta import read_feed


async def import_feed(feed_path: Path) -> tuple[int, int]:
    dataset = await asyncio.to_thread(read_feed, feed_path)
    async with SessionLocal() as session:
        await replace_transjakarta_dataset(session, dataset)
        await session.commit()
    return len(dataset.stops), len(dataset.segments)


async def import_url(url: str) -> tuple[int, int]:
    with tempfile.TemporaryDirectory(prefix="transjakarta-gtfs-") as directory:
        feed_path = Path(directory) / "transjakarta.zip"
        await asyncio.to_thread(urlretrieve, url, feed_path)
        return await import_feed(feed_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, help="Path to a previously downloaded GTFS zip")
    parser.add_argument(
        "--url",
        default=get_settings().transjakarta_gtfs_url,
        help="Official GTFS URL to download when --feed is omitted",
    )
    args = parser.parse_args()

    if args.feed:
        stops, segments = asyncio.run(import_feed(args.feed))
    else:
        stops, segments = asyncio.run(import_url(args.url))
    print(f"Imported {stops} stops and {segments} directed segments.")


if __name__ == "__main__":
    main()
