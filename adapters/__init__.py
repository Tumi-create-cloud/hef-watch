"""Platform adapters. To add a platform: create adapters/<name>.py with KEY, NAME, PREFIX, EVERY_S and
fetch() -> (listings, source, partial, warnings), using common.listing(); then add it to ADAPTERS."""
from . import hef, vbt, schep, athome, ikwilhuren, vesteda

# ikwilhuren uit 25-10-2026 (403 sinds 25-10 04:30), weer aan 26-10-2026 op verzoek van Tum
ADAPTERS = [hef, vbt, schep, athome, ikwilhuren, vesteda]
