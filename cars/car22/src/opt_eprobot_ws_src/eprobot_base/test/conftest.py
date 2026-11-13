"""pytest bootstrap for the pure-Python ISCC_CAR chassis driver tests.

``eprobot_base`` is a plain source package (it is not installed into
site-packages), so make the directory that *contains* it importable no matter
where pytest is invoked from.  Running the suite with
``PYTHONPATH=<pkg root> python3 -m pytest test -q`` from the package directory
works as well; this hook just makes that PYTHONPATH optional.
"""

import os
import sys

# <pkg root>/test/conftest.py -> <pkg root>/test -> <pkg root>
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
