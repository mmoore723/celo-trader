#!/bin/bash
cd "$(dirname "$0")"
count=$(ls .fuse_hidden* 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -eq 0 ]; then
  echo "Nothing to clean up."
else
  rm -f .fuse_hidden*
  echo "Removed $count .fuse_hidden files from $(pwd)"
fi
