import os
import shutil


def recursive_scandir(top_dir, dir_first=True):
  """Recursively scan a path.

  Args:
      top_dir: The path to scan.
      dir_first: If true, yield a directory before its contents.
          Otherwise, yield a directory's contents before the
          directory itself.

  Returns:
      A generator of tuples of a path relative to the top path, and an
      os.DirEntry object of the file or directory at that path. The
      top_dir itself is not included.
  """

  def f(relpath, dir_entry):
    if dir_first and dir_entry is not None:
      yield relpath, dir_entry

    path = os.path.join(top_dir, relpath)

    for entry in os.scandir(path):
      entry_relpath = os.path.join(relpath, entry.name)

      if entry.is_dir():
        for item in f(entry_relpath, entry):
          yield item
      else:
        yield entry_relpath, entry

    if not dir_first and dir_entry is not None:
      yield relpath, dir_entry

  return f('', None)


def fix_dir_stats(profile):
  """Fix directory stats for a profile.

  This function assumes that every directory in the output corresponds
  to a directory in the input with the same relative path. If that is
  not true for the profile, do not use this function.

  For each directory in profile.dst_path(), this will copy stats from
  the corresponding directory in profile.src_path().
  """

  for dst_relpath, dst_entry in recursive_scandir(profile.dst_path()):
    if not dst_entry.is_dir():
      continue

    src_relpath = dst_relpath

    shutil.copystat(
      profile.src_path(src_relpath),
      profile.dst_path(dst_relpath),
      )
