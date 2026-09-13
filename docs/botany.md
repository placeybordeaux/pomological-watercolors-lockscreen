# The species notes

Compositions with room for them carry a note about the species, in two halves
kept deliberately apart.

**The sentence** is authored, in `data/botany.json`, one per `common_name`. It
is held to what is uncontroversial about the plant or its arrival in American
orchards — never about the individual variety, which would be 7,584 claims
nobody can check.

**The fact** underneath is computed from the catalogue at render time: how many
plates of this species there are, and the years they span. It is never
hand-maintained, so it cannot drift as more scans are prepared.

```
The sweet cherry ... untended trees reach 30 metres, which is why old
orchards needed ladders.
163 of the collection's 7,584 plates, painted 1892–1939.
```

59 entries cover **98.2%** of the plates, because the collection is wildly
skewed: apples alone are half of it, and twenty species are 95%. A species with
no entry gets no note and the layout closes the gap.

`diptych` sets the note as a museum label in the empty column between the two
sheets. `ledger` gives it reading size in the left field. `mat` hangs it under
the caption. `board`, `cabinet` and `bleed` have no room and omit it.

## Adding one

One line of JSON, keyed on the `common_name` exactly as the catalogue spells
it:

```json
"quinces": "Too hard and sour to eat raw, but its flesh turns pink and
            perfumed with long cooking; the word marmalade comes from
            marmelo, the Portuguese for quince."
```

`sqlite3 data/pom.sqlite "select distinct common_name from items"` lists what
is spellable. Keep to the plant, not the cultivar, and prefer the dull true
claim to the interesting shaky one — these render at 22px on a lock screen
where nobody can check them.
