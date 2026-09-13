# Why it looks the way it does

## The aspect problem

The paintings are portrait, median aspect **0.65**. Screens are not.

A phone at ~0.46 is *narrower* than the paintings, so filling it crops the
width — that was the original problem, and it is the smaller one. An ultrawide
monitor is the opposite: at 3440 × 1440 the screen is 2.39:1, three and a half
plates wide, so stretching one painting across it throws away about **85% of
the image**.

So none of the six treatments fill the screen with a single plate. Each is a
different answer to "what goes in all that width", ordered here by how far they
drift from "a painting on a wall".

| Treatment | The bet | The cost |
| --- | --- | --- |
| `mat` | Don't crop a public-domain painting at all. Float the whole sheet on a mat sampled from its own paper and let the rest be wall. | Most of a very wide screen is deliberately empty. |
| `ledger` | Run the sheet off the right edge and make the ground its own paper tone, so the screen reads as one sheet painted at one end. | You see about four fifths of the painting, and the left two thirds carry only type. |
| `board` | Four specimens in a row, heights nudged by hand. The only treatment that uses 2.39:1 because it is 2.39:1 rather than in spite of it. | Four plates at once is four times the visual noise. |
| `diptych` | Two varieties of one fruit facing across a centre rule. The collection was made for comparison; this is the only treatment that does any. | Needs two plates of one species in the pool. Reads as a museum label. |
| `cabinet` | Fourteen plates on the copy-stand black, as a drawer pulled out of the cabinet. | At thumbnail size the paintings stop being paintings, and it fights every light window on top of it. |
| `bleed` | Edge to edge after all — but on a detail. The busiest band of the plate is where the fruit is. | Throws away the sheet, the handwriting and the signature. |

## It changes in the dark

A wallpaper that swaps while you are reading the screen is a distraction, and
the fix is not a slower timer — it is to **only ever change across a dark
boundary**.

The watcher listens for the screen locking (`ActiveChanged`, on whichever of
the `org.xfce` / `org.gnome` / `org.freedesktop` screensaver interfaces your
desktop announces it on) and composes the next plate *then*, gated to at most
one change an hour. Unlocking reveals a picture that was already there.

`--mode timer` exists for desktops that do not announce locking on D-Bus, and
is worse for exactly the reason above.

## It shows you everything before it repeats

Selection walks a shuffled ring and retires **only the plates it actually
displays** — 2 for a diptych, 14 for a cabinet. Nothing repeats until
everything has been seen: at one change an hour over the full collection,
**224 days**.

This is less obvious than it sounds. An earlier version walked a cursor and
skipped past entries a treatment could not use, counting them as shown. Asking
for two plates of one fruit retired 708 paintings nobody had seen and lapped
the collection in a day. The ring now removes exactly what it returns.

Preparing more scans shuffles them into the unshown set rather than restarting,
and what is persisted is the set of plates already *shown* — the ring is just
the remainder, reshuffled each run.

## Where text goes

`prepare` measures a luminance/detail grid and the paper tone for every plate.
A composition uses that three ways: the paper tone sets the mat colour, the
detail grid finds the quiet regions where text will not fight brushwork, and
for `bleed` it picks the band of the plate that holds the fruit.

`bleed` is also the only treatment where a caption has to survive whatever is
underneath it. It measures the luminance under the caption and pushes the paper
*further in the ink's own direction* — light paper lighter under dark ink —
rather than laying a grey veil over cream paper, which reads as dirt.
