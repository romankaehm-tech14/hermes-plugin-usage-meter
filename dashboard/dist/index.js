// Usage Meter — dashboard half is API-only (no tab). This stub keeps the
// manifest's `entry` resolvable; the real UI lives in the Desktop composer.
(function () {
  if (window.__HERMES_PLUGINS__) {
    window.__HERMES_PLUGINS__.register('usage-meter', function () {
      return null
    })
  }
})()
