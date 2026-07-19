"""Parquet-backed caching so we never re-hit rate-limited APIs on a re-run.

Two entry points:
  * ``cached_frame(key, builder, subdir=...)`` — call ``builder()`` only if the
    parquet file is missing (or ``force=True``), else load from disk.
  * ``@disk_cache(...)`` — decorator form for functions that return a DataFrame.

Keys are turned into safe filenames. Everything lands under ``data/<subdir>/``.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from refedge.config import RAW, INTERIM, FEATURES

_SUBDIRS = {"raw": RAW, "interim": INTERIM, "features": FEATURES}


def _safe(key: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("_")
    if len(slug) > 120:  # keep filenames sane; disambiguate with a hash
        h = hashlib.sha1(key.encode()).hexdigest()[:10]
        slug = f"{slug[:100]}_{h}"
    return slug


def path_for(key: str, subdir: str = "raw") -> Path:
    base = _SUBDIRS.get(subdir, RAW)
    return base / f"{_safe(key)}.parquet"


def cached_frame(
    key: str,
    builder: Callable[[], pd.DataFrame],
    subdir: str = "raw",
    force: bool = False,
) -> pd.DataFrame:
    """Return the cached DataFrame for ``key``, building + persisting it if absent.

    ``builder`` is only invoked on a cache miss (or ``force``), so wrapping an API
    pull in this makes re-runs free and keeps us under rate limits.
    """
    fp = path_for(key, subdir)
    if fp.exists() and not force:
        return pd.read_parquet(fp)
    df = builder()
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"builder for {key!r} returned {type(df)}, expected DataFrame")
    fp.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(fp, index=False)
    return df


def disk_cache(subdir: str = "raw", key: str | None = None):
    """Decorator: cache a DataFrame-returning function keyed by name + args.

    Pass ``force=True`` at call time to bypass the cache and rebuild.
    """
    def deco(fn: Callable[..., pd.DataFrame]):
        def wrapper(*args, force: bool = False, **kwargs):
            parts = [key or fn.__name__]
            parts += [str(a) for a in args]
            parts += [f"{k}={v}" for k, v in sorted(kwargs.items())]
            cache_key = "__".join(parts)
            return cached_frame(cache_key, lambda: fn(*args, **kwargs), subdir, force)
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return deco
