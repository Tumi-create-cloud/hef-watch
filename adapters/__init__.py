"""Platform adapters. To add a platform: create adapters/<name>.py with KEY, NAME, PREFIX, EVERY_S and
fetch() -> (listings, source, partial, warnings), using common.listing(); then add it to ADAPTERS."""
from . import hef, vbt, schep, athome, ikwilhuren, vesteda

# Gepauzeerd 21-10-2026 op verzoek van Tum (sites plat): hef, schep, ikwilhuren
ADAPTERS = [vbt, athome, vesteda]
