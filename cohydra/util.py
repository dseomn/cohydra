import os


def recursive_scandir(top_dir, dir_first=True):
  """Recursively scan a path.

  Args:
      top_dir: The path to scan.
      dir_first: If true, yield a directory before its contents.
          Otherwise, yield a directory's contents before the
          directory itself.

  Returns:
      A generator of tuples of the path of a directory relative to
      the top path, and an os.DirEntry object of an entry in that
      directory. The top_dir itself is not included.
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
