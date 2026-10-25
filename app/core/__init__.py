"""
app.core
========
Cross-cutting, framework-level building blocks shared by every module in
the platform: configuration, security primitives, structured logging,
the exception hierarchy, domain-wide constants/enums, the in-process event
bus, and HTTP middleware.

Nothing in `app.core` is allowed to import from `app.agents`, `app.services`,
`app.repositories`, or `app.api`. This keeps `core` a true dependency sink
(everything depends on it, it depends on nothing internal) which is what
lets every other layer be tested and swapped independently.
"""
