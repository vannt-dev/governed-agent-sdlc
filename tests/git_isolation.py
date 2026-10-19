"""Keeps the git commands of the tests on their own temporary repositories.

Git runs hooks with variables such as GIT_DIR and GIT_INDEX_FILE set. Inside a submodule GIT_DIR is
an absolute path, so a test that runs `git init <tmp>` or `git -C <tmp> add` from a pre-push hook
would work on the repository running the hook instead of its temporary one. Importing this module
removes those variables for the whole test process (the list is `git rev-parse --local-env-vars`).
"""

import os

REPOSITORY_VARIABLES = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)

for name in REPOSITORY_VARIABLES:
    os.environ.pop(name, None)
