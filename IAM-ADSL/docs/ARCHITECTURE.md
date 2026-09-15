# Architecture

`app.py` is the only development entry point. The Selenium workflow is in
`src/iam_adsl/routes.py` while it is progressively extracted into services,
without changing operational WimTech selectors.

New code is organised as follows:

```
src/iam_adsl/
  templates/       Flask-rendered HTML pages
  routes.py        HTTP routes and compatibility workflow
  config.py       Runtime URLs, paths, and timeouts
  application.py  Flask application factory
  services/       Reusable domain and external-system services
    pdf_extractor.py
tests/            Unit and integration tests
scripts/          Local setup commands
```

The next safe extraction is to move CMD search and Etude functions into an
`automation` service, then expose Flask routes through blueprints. This keeps
the browser behaviour unchanged while reducing the current monolithic module.
