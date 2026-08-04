"""SongGenerator -- replace a song's vocals with sung Finnish word samples."""

import os

# Demucs pulls its checkpoints through huggingface_hub, which warns on every run
# that Windows without Developer Mode cannot use symlinks for its cache. Nothing
# here is affected by that. Must be set before huggingface_hub is first imported,
# which is why it lives at package import rather than at the call site.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

__version__ = "0.1.0"
