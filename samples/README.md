# samples

Scratch space for test renders. Nothing here is committed except this file
(`.gitignore` ignores everything else in this directory) so the repository
stays free of binary blobs.

Make a synthetic test image:

```bat
python tests\make_sample.py samples\input.png 800 600
```

Then render some styles into the same folder:

```bat
python app_cli.py generate samples\input.png --style oil_painting --style pixel_art ^
    -n 2 --max-side 600 -o samples\out --sheet samples\out\sheet.png
```

Or just use your own photo - any of `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`,
`.tif`, `.gif`, `.ppm`.
