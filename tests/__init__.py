"""Every test run gets its own config home: nothing here may read or write the author's
real project registry (~/.config/km/projects.json). Tests that care set their own."""

import os
import tempfile

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="km-tests-xdg-")
