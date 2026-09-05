# Collection and deck finder refinement — September 4, 2026

RiftDesk should help a player find a useful deck before they have catalogued their whole collection. The finder starts from tournament evidence, asks about relevant quantities, and makes collection assumptions visible.

## Changes

- A visible card-pool summary links to the existing collection settings. Recorded quantities, collection shortcuts, and unrestricted access have different labels.
- Legend search has a no-results recovery and a way to browse every legend. Existing matchup-based sorting is preserved.
- Explicit zero answers are recognised immediately. Counting a card no longer reorders the grid or loses keyboard focus. Follow-up questions explain their own defaults.
- The completed list is available before saving. Exact quantities can be saved to the collection from that screen.
- Card-mode changes preserve both ownership and exclusion settings in the API and repository. Queued frontend writes prevent rapid edits from replacing one another.
- Resetting a collection removes ownership shortcuts in every mode, closes deleted finder sessions, and keeps saved decks and exclusions.
- The builder displays missing copies without requiring the legality panel to be opened.

## Verified rules

The [official Rules Hub](https://playriftbound.com/en-us/rules-hub/) links to the July 16, 2026 [Tournament Rules](https://cmsassets.rgpub.io/sanity/files/dsfx7636/news_live/503da65669ced10598d62925a6f6bc15111af726.pdf). Sections 402.1 and 601.1 require 40 main-deck cards including the chosen champion, one legend, 12 runes, and three differently named battlefields. Section 601.1.c.1 permits **10 or fewer sideboard cards**. The old eight-card advisory has been removed.

The [July ban announcement](https://playriftbound.com/en-us/news/announcements/july-ban-list-updates/) added Stealthy Pursuer, The Arena's Greatest, and Aspirant's Climb effective **July 24, 2026**. These now appear in the constructed ban list and a dated meta era. Earlier historical lists remain in the archive.

## Data and deployment

The existing Railway service serves both the Python API and the built frontend. No new service, database migration, identity-cookie change, or collection-data migration is needed. Anonymous records still belong to the browser identity; the collection panel now explains this and points users to deck exports and share links.

## Validation

Frontend checks include TypeScript and the existing Node tests, plus regressions for explicit zero counts, assumed ownership, and queued writes. Backend regressions exercise every card mode, reload persistence, exclusion actions, and reset behavior. The July sideboard profile is checked against the verified limit.
