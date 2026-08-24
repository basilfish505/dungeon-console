"""Test package — skip full world persistence boot when importing dungeon_crawler."""
import os

os.environ.setdefault('PERMAQUEST_SKIP_WORLD_BOOT', '1')
os.environ.setdefault('PERMAQUEST_SKIP_LEGACY_MIGRATION', '1')
