"""The local engine: Whisper, run on this machine through faster-whisper.

Nothing here is imported unless the caller chose `--provider local`, and
`faster_whisper` itself is imported only inside the two functions that need it, so
the default install (which does not carry it) never notices this module exists.

Two rules shape it:

- **A model is downloaded by `pull`, never by a transcription.** `run` builds the
  engine from a directory that is already on disk and refuses if it is not. That
  check comes first and is not optional: `WhisperModel` treats any path that is not
  a directory as a model *name* and downloads it, and a directory with no
  `tokenizer.json` makes it fetch a tokenizer from the network. Either would put a
  download inside a `recv --follow` loop, stalling the first voice note for minutes
  with no explanation.
- **A half-finished download must not look like a model.** `pull` writes to
  `<size>.partial` and renames it into place only once every file is there.

Only sizes that are honest about English are offered. There is no `.en` variant:
an English-only model decodes Urdu as confident, fluent English, which is the
failure this package refuses everywhere else.
"""

import importlib.util
import shutil
import sys

from .errors import WhatsAppError
from .state import models_dir

# Approximate download in MB, said out loud before a pull starts. They are the
# published figures, not measured here.
SIZES = {"tiny": 75, "base": 150, "small": 500}
DEFAULT_SIZE = "base"

# What `download_model` fetches that the engine needs to run offline. The tokenizer
# is on the list because without it the engine goes to the network for one.
NEEDED_FILES = ("model.bin", "config.json", "tokenizer.json")

EXTRA_HINT = 'install the extra: pip install "wa-agent[local]"'

# One loaded model per directory for the life of the process: a `--follow` loop pays
# the load once, not per voice note.
_loaded = {}


def check_size(size):
    """The size, or a `bad_usage` naming the ones offered."""
    if size not in SIZES:
        raise WhatsAppError("bad_usage", f"unknown local model size {size!r}; offered: {', '.join(SIZES)}")
    return size


def extra_installed():
    """Whether `faster_whisper` can be imported, without importing it."""
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except (ImportError, ValueError):
        return False


def model_path(size, env=None):
    return models_dir(env, create=False) / size


def is_ready(size, env=None):
    """A model is ready when every file the engine needs is present. Stat calls only."""
    path = model_path(size, env)
    return all((path / name).is_file() for name in NEEDED_FILES)


def installed_sizes(env=None):
    return [size for size in SIZES if is_ready(size, env)]


def check_ready(size, env=None):
    """Raise `local_not_ready` naming the fix, or return. Cheap: no engine import."""
    if not extra_installed():
        raise WhatsAppError("local_not_ready", f"the local engine is not installed; {EXTRA_HINT}")
    if not is_ready(size, env):
        raise WhatsAppError("local_not_ready",
                            f'the "{size}" model is not downloaded; run: wa-agent model pull {size}')


def pull(size=None, env=None, out=None):
    """Download one model, saying its size first. Returns the directory it is in."""
    out = sys.stderr if out is None else out
    size = check_size(size or DEFAULT_SIZE)
    if not extra_installed():
        raise WhatsAppError("local_not_ready", f"the local engine is not installed; {EXTRA_HINT}")
    target = model_path(size, env)
    if is_ready(size, env):
        print(f'the "{size}" model is already downloaded: {target}', file=out, flush=True)
        return target

    print(f'downloading the "{size}" Whisper model, about {SIZES[size]} MB, to {target}', file=out, flush=True)
    try:
        from faster_whisper import download_model
    except ImportError as exc:
        raise WhatsAppError("local_not_ready", f"the local engine could not be imported: {exc}; {EXTRA_HINT}") from exc

    models_dir(env)  # create the parent, and only now that a download is really starting
    partial = target.with_name(f"{size}.partial")
    shutil.rmtree(partial, ignore_errors=True)  # what an earlier attempt that died left behind
    try:
        download_model(size, output_dir=str(partial))
        missing = [name for name in NEEDED_FILES if not (partial / name).is_file()]
        if missing:
            raise RuntimeError(f"the download is missing {', '.join(missing)}")
        shutil.rmtree(target, ignore_errors=True)  # a directory that was there but not ready
        partial.rename(target)
    except Exception as exc:  # noqa: BLE001 - the hub client raises many types; all mean "not downloaded"
        shutil.rmtree(partial, ignore_errors=True)
        raise WhatsAppError("transcription_unavailable",
                            f"model download failed: {type(exc).__name__}: {exc}") from exc
    print(f"done: {target}", file=out, flush=True)
    return target


def _model(size, env):
    path = str(model_path(size, env))
    if path not in _loaded:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise WhatsAppError("local_not_ready", f"the local engine could not be imported: {exc}; {EXTRA_HINT}") from exc
        try:
            # A directory that exists (checked by the caller), on the CPU, quantised: a
            # relay is not the place for a GPU or a gigabyte of float weights.
            _loaded[path] = WhisperModel(path, device="cpu", compute_type="int8")
        except Exception as exc:  # noqa: BLE001
            raise WhatsAppError("transcription_failed",
                                f"the local model could not be loaded: {type(exc).__name__}: {exc}") from exc
    return _loaded[path]


def run(path, size=None, language=None, env=None):
    """Audio file in, text out (possibly empty: the caller decides what empty means).

    `language` is a Whisper code such as `ur`; left out, the engine detects it.
    `vad_filter` is on because the engine's default is off, and a Whisper model fed
    silence will happily write a sentence.
    """
    size = check_size(size or DEFAULT_SIZE)
    check_ready(size, env)   # before the engine is even imported: see the module docstring
    model = _model(size, env)
    try:
        # `segments` is a generator: the audio is not decoded until it is consumed.
        segments, _info = model.transcribe(str(path), language=language or None, vad_filter=True)
        pieces = (segment.text.strip() for segment in segments)
        return " ".join(piece for piece in pieces if piece)
    except WhatsAppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WhatsAppError("transcription_failed", f"local transcription failed: {type(exc).__name__}: {exc}") from exc
