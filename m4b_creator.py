#!/usr/bin/env python3
"""
M4B Creator - Create M4B audiobook files from audio chapters using ffmpeg.
Each audio file becomes a chapter in the resulting M4B file.
Supports MP3, FLAC, M4A, M4B, AAC, OGG, Opus, and WAV input.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Callable

import mutagen
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.wave import WAVE

SUPPORTED_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.m4b', '.aac', '.ogg', '.opus', '.wav'}


logger = logging.getLogger(__name__)


class M4BCreator:
    """Creates M4B audiobook files from MP3 chapter files."""

    def __init__(self, verbose: bool = False):
        if verbose:
            logger.setLevel(logging.DEBUG)
            if not logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                ))
                logger.addHandler(handler)
        self.verbose = verbose
        logger.debug("Initializing M4BCreator")e
        self._verify_ffmpeg()

    def _verify_ffmpeg(self):
        """Verify ffmpeg is available."""
        logger.debug("Checking for ffmpeg installation")
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, check=True, text=True
            )
            logger.debug("ffmpeg found: %s", result.stdout.split('\n')[0])
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg not found. Install it:\n"
                "  macOS: brew install ffmpeg\n"
                "  Ubuntu: sudo apt-get install ffmpeg\n"
                "  Windows: download from https://ffmpeg.org/download.html"
            )

    def get_audio_duration(self, file_path: str) -> float:
        """Get duration of an audio file in seconds."""
        logger.debug("Getting duration for: %s", file_path)
        audio = mutagen.File(file_path)
        if audio is None:
            raise ValueError(f"Unsupported audio format: {file_path}")
        logger.debug("Duration of %s: %.2fs", Path(file_path).name, audio.info.length)
        return audio.info.length

    # Keep old name as alias for compatibility
    get_mp3_duration = get_audio_duration

    def extract_metadata(self, file_path: str) -> Dict:
        """Extract metadata tags from an audio file."""
        logger.debug("Extracting metadata from: %s", file_path)
        audio = mutagen.File(file_path)
        if audio is None:
            logger.debug("No metadata found for: %s", file_path)
            return {}

        # MP3 uses ID3 frames
        if isinstance(audio, MP3):
            tags = self._extract_id3_metadata(audio)
            logger.debug("ID3 metadata for %s: %s", Path(file_path).name, tags)
            return tags

        # MP4/M4A/M4B/AAC
        if isinstance(audio, MP4):
            tags = self._extract_mp4_metadata(audio)
            logger.debug("MP4 metadata for %s: %s", Path(file_path).name, tags)
            return tags

        # FLAC, OGG, Opus use Vorbis-style tags
        tags = self._extract_vorbis_metadata(audio)
        logger.debug("Vorbis metadata for %s: %s", Path(file_path).name, tags)
        return tags

    # Keep old name as alias for compatibility
    extract_mp3_metadata = extract_metadata

    def _extract_id3_metadata(self, audio: MP3) -> Dict:
        tags = {}
        if audio.tags is None:
            return tags

        tag_map = {
            'TIT2': 'title',
            'TALB': 'album',
            'TPE1': 'artist',
            'TPE2': 'albumartist',
            'TCOM': 'composer',
            'TCON': 'genre',
            'TDRC': 'date',
            'TPUB': 'publisher',
            'TLAN': 'language',
        }

        for id3_key, name in tag_map.items():
            if id3_key in audio.tags:
                frame = audio.tags[id3_key]
                if hasattr(frame, 'text') and frame.text:
                    tags[name] = str(frame.text[0])

        for key in audio.tags:
            if key.startswith('COMM'):
                frame = audio.tags[key]
                if hasattr(frame, 'text') and frame.text:
                    tags['comment'] = str(frame.text[0])
                break

        return tags

    def _extract_mp4_metadata(self, audio: MP4) -> Dict:
        tags = {}
        if audio.tags is None:
            return tags

        tag_map = {
            '\xa9nam': 'title',
            '\xa9alb': 'album',
            '\xa9ART': 'artist',
            'aART': 'albumartist',
            '\xa9wrt': 'composer',
            '\xa9gen': 'genre',
            '\xa9day': 'date',
            '\xa9cmt': 'comment',
        }

        for mp4_key, name in tag_map.items():
            if mp4_key in audio.tags:
                val = audio.tags[mp4_key]
                if val:
                    tags[name] = str(val[0])

        return tags

    def _extract_vorbis_metadata(self, audio) -> Dict:
        tags = {}
        if audio.tags is None:
            return tags

        tag_map = {
            'title': 'title',
            'album': 'album',
            'artist': 'artist',
            'albumartist': 'albumartist',
            'composer': 'composer',
            'genre': 'genre',
            'date': 'date',
            'publisher': 'publisher',
            'language': 'language',
            'comment': 'comment',
            'description': 'comment',
        }

        for vorbis_key, name in tag_map.items():
            if vorbis_key in audio.tags:
                val = audio.tags[vorbis_key]
                if val:
                    tags[name] = str(val[0])

        return tags

    def extract_cover(self, file_path: str) -> Optional[bytes]:
        """Extract embedded cover art from an audio file. Returns raw image bytes."""
        logger.debug("Extracting cover art from: %s", file_path)
        audio = mutagen.File(file_path)
        if audio is None:
            logger.debug("No audio data found for cover extraction: %s", file_path)
            return None

        # MP3 - ID3 APIC frames
        if isinstance(audio, MP3):
            if audio.tags is None:
                return None
            apic_frames = audio.tags.getall('APIC')
            if apic_frames:
                return apic_frames[0].data

        # MP4/M4A/M4B - covr atom
        elif isinstance(audio, MP4):
            if audio.tags and 'covr' in audio.tags:
                covers = audio.tags['covr']
                if covers:
                    return bytes(covers[0])

        # FLAC - picture blocks
        elif isinstance(audio, FLAC):
            if audio.pictures:
                return audio.pictures[0].data

        # OGG/Opus - METADATA_BLOCK_PICTURE
        elif isinstance(audio, (OggVorbis, OggOpus)):
            if audio.tags and 'metadata_block_picture' in audio.tags:
                import base64
                from mutagen.flac import Picture
                data = base64.b64decode(audio.tags['metadata_block_picture'][0])
                pic = Picture(data)
                return pic.data

        return None

    # Keep old name as alias for compatibility
    extract_mp3_cover = extract_cover

    def create(
        self,
        mp3_files: Optional[List[str]] = None,
        output_path: str = "",
        chapter_titles: Optional[List[str]] = None,
        title: Optional[str] = None,
        author: Optional[str] = None,
        narrator: Optional[str] = None,
        year: Optional[str] = None,
        comment: Optional[str] = None,
        cover_path: Optional[str] = None,
        bitrate: str = "128k",
        progress_callback: Optional[Callable[[str, float], None]] = None,
        audio_files: Optional[List[str]] = None,
        use_tags: bool = False,
    ) -> str:
        """Create an M4B file from a list of audio files.

        Args:
            audio_files: Ordered list of audio file paths (one per chapter).
            mp3_files: Alias for audio_files (for backward compatibility).
            output_path: Path for the output .m4b file.
            chapter_titles: Optional chapter titles (defaults to filenames).
            title: Book title metadata.
            author: Author/artist metadata.
            narrator: Narrator (stored as album_artist).
            year: Year metadata.
            comment: Comment/description metadata.
            cover_path: Path to cover image (jpg/png).
            bitrate: AAC encoding bitrate (default 128k).
            progress_callback: Optional callback(status_text, fraction_done).
            use_tags: Use audio title tags as chapter names (ignored if chapter_titles is provided).

        Returns:
            Path to the created M4B file.
        """

        def _progress(msg: str, frac: float):
            if progress_callback:
                progress_callback(msg, frac)

        # Support both parameter names
        files = audio_files or mp3_files
        if not files:
            raise ValueError("No audio files provided")

        logger.debug("create() called with %d files, output=%s", len(files), output_path)
        logger.debug("Options: bitrate=%s, use_tags=%s, cover_path=%s", bitrate, use_tags, cover_path)
        logger.debug("Metadata: title=%s, author=%s, narrator=%s, year=%s", title, author, narrator, year)

        for f in files:
            if not os.path.isfile(f):
                raise FileNotFoundError(f"File not found: {f}")
            ext = Path(f).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"Unsupported audio format '{ext}': {f}")
            logger.debug("Validated input file: %s (%s)", f, ext)

        if use_tags and not chapter_titles:
            chapter_titles = []
            for f in files:
                try:
                    tags = self.extract_metadata(f)
                    chapter_titles.append(tags.get("title", Path(f).stem))
                except Exception:
                    chapter_titles.append(Path(f).stem)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Step 1: Build chapter info and concat list
            _progress("Analyzing audio files...", 0.0)
            chapters = []
            current_time_ms = 0

            concat_list_path = os.path.join(tmp_dir, "concat.txt")
            with open(concat_list_path, "w") as f:
                for idx, audio_path in enumerate(files):
                    duration = self.get_audio_duration(audio_path)
                    duration_ms = int(duration * 1000)

                    if chapter_titles and idx < len(chapter_titles):
                        ch_title = chapter_titles[idx]
                    else:
                        ch_title = Path(audio_path).stem

                    chapters.append({
                        "title": ch_title,
                        "start_ms": current_time_ms,
                        "end_ms": current_time_ms + duration_ms,
                    })
                    logger.debug(
                        "Chapter %d: '%s' [%dms - %dms] (%.2fs)",
                        idx + 1, ch_title, current_time_ms,
                        current_time_ms + duration_ms, duration,
                    )
                    current_time_ms += duration_ms

                    # ffmpeg concat demuxer format — must use absolute paths
                    abs_path = os.path.abspath(audio_path)
                    safe_path = abs_path.replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")

            logger.debug("Total duration: %dms across %d chapters", current_time_ms, len(chapters))
            logger.debug("Concat list written to: %s", concat_list_path)

            # Step 2: Concatenate audio files and encode to M4A/AAC
            # Check if all files are already AAC (m4a/m4b/aac) — can stream-copy
            all_aac = all(
                Path(f).suffix.lower() in {'.m4a', '.m4b', '.aac'}
                for f in files
            )
            logger.debug("All files are AAC (stream copy): %s", all_aac)

            if all_aac:
                _progress("Concatenating AAC files (stream copy)...", 0.1)
            else:
                _progress("Concatenating and encoding to AAC...", 0.1)

            intermediate_m4a = os.path.join(tmp_dir, "combined.m4a")
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
            ]

            if all_aac:
                cmd.extend(["-c:a", "copy"])
            else:
                cmd.extend(["-c:a", "aac", "-b:a", bitrate])

            cmd.extend(["-movflags", "+faststart", intermediate_m4a])

            logger.debug("Running ffmpeg encode: %s", " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.debug("ffmpeg encode stderr:\n%s", result.stderr)
                raise RuntimeError(f"ffmpeg encoding failed:\n{result.stderr}")
            logger.debug("Encoding complete: %s", intermediate_m4a)

            _progress("Adding chapter markers...", 0.5)

            # Step 3: Write ffmpeg chapter metadata file
            metadata_path = os.path.join(tmp_dir, "chapters.txt")
            with open(metadata_path, "w") as f:
                f.write(";FFMETADATA1\n")

                if title:
                    f.write(f"title={title}\n")
                    f.write(f"album={title}\n")
                if author:
                    f.write(f"artist={author}\n")
                    if not narrator:
                        f.write(f"album_artist={author}\n")
                if narrator:
                    f.write(f"album_artist={narrator}\n")
                if year:
                    f.write(f"date={year}\n")
                if comment:
                    f.write(f"comment={comment}\n")

                f.write("\n")

                for ch in chapters:
                    f.write("[CHAPTER]\n")
                    f.write("TIMEBASE=1/1000\n")
                    f.write(f"START={ch['start_ms']}\n")
                    f.write(f"END={ch['end_ms']}\n")
                    f.write(f"title={ch['title']}\n\n")

            logger.debug("Chapter metadata written to: %s", metadata_path)

            # Step 4: Mux chapters (and optionally cover art) into final M4B
            _progress("Writing M4B file...", 0.7)

            cmd = [
                "ffmpeg", "-y",
                "-i", intermediate_m4a,
                "-i", metadata_path,
            ]

            # Add cover art input if provided
            if cover_path and os.path.isfile(cover_path):
                logger.debug("Embedding cover art from: %s", cover_path)
                cmd.extend(["-i", cover_path])
                cmd.extend([
                    "-map", "0:a",
                    "-map", "2:v",
                    "-c:a", "copy",
                    "-c:v", "mjpeg",
                    "-disposition:v:0", "attached_pic",
                ])
            else:
                cmd.extend([
                    "-map", "0:a",
                    "-c:a", "copy",
                ])

            cmd.extend([
                "-map_metadata", "1",
                "-movflags", "+faststart",
                output_path,
            ])

            logger.debug("Running ffmpeg mux: %s", " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.debug("ffmpeg mux stderr:\n%s", result.stderr)
                raise RuntimeError(f"ffmpeg chapter muxing failed:\n{result.stderr}")

            logger.debug("M4B created successfully: %s", output_path)
            _progress("Done!", 1.0)

        return output_path


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Create an M4B audiobook from audio chapter files"
    )
    parser.add_argument("output", help="Output .m4b file path")
    parser.add_argument("files", nargs="+", help="Audio chapter files (in order)")
    parser.add_argument("-t", "--title", help="Book title")
    parser.add_argument("-a", "--author", help="Author name")
    parser.add_argument("-n", "--narrator", help="Narrator name")
    parser.add_argument("-y", "--year", help="Year")
    parser.add_argument("-c", "--comment", help="Comment or description")
    parser.add_argument("--cover", help="Cover image path (jpg/png)")
    parser.add_argument("--bitrate", default="128k",
                        help="AAC bitrate (default: 128k, ignored for AAC input)")
    parser.add_argument("--use-tags", action="store_true",
                        help="Use audio title tags as chapter names")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")

    args = parser.parse_args()
    args.files = sorted(args.files)

    creator = M4BCreator(verbose=args.verbose)

    # Auto-populate metadata from first file if not provided
    try:
        tags = creator.extract_metadata(args.files[0])
        if not args.title:
            args.title = tags.get("album") or tags.get("title")
        if not args.author:
            args.author = tags.get("artist") or tags.get("albumartist")
        if not args.year:
            args.year = tags.get("date")
    except Exception:
        pass

    # Auto-extract cover art from first file if not provided
    if not args.cover:
        try:
            cover_data = creator.extract_cover(args.files[0])
            if cover_data:
                ext = ".png" if cover_data[:8] == b'\x89PNG\r\n\x1a\n' else ".jpg"
                cover_tmp = os.path.join(tempfile.gettempdir(), f"m4b_cover{ext}")
                with open(cover_tmp, "wb") as cf:
                    cf.write(cover_data)
                args.cover = cover_tmp
                print(f"Extracted cover art from {Path(args.files[0]).name}")
        except Exception:
            pass

    creator.create(
        audio_files=args.files,
        output_path=args.output,
        use_tags=args.use_tags,
        title=args.title,
        author=args.author,
        narrator=args.narrator,
        year=args.year,
        comment=args.comment,
        cover_path=args.cover,
        bitrate=args.bitrate,
        progress_callback=lambda msg, _: print(msg),
    )
    print(f"Created: {args.output}")


if __name__ == "__main__":
    main()
