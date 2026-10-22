"""Platform adapters. To add a platform: create adapters/<name>.py with KEY, NAME, PREFIX, EVERY_S and
fetch() -> (listings, source, partial, warnings), using common.listing(); then add it to ADAPTERS."""
from . import hef, vbt, schep, athome, ikwilhuren, vesteda

# Hef+Schep weer aan 22-10-2026 (storing was PHP-lek); ikwilhuren gepauzeerd tot Tum beslist
ADAPTERS = [hef, vbt, schep, athome, vesteda]
