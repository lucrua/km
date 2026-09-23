# build-cm

Vendors CodeMirror 6 and its Markdown/merge extensions into one ES module, `km/vendor/cm.js`.

Rebuild with `npm ci && npm run build` — `npm ci` installs exactly what `package-lock.json` pins.

`node_modules/` is not committed; only the built `km/vendor/cm.js` is.
