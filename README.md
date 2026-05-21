# choco-treats

A collection of helper tools for working with Chocolatey/NuGet packages in local or offline environments, focused on self-hosted package handling without reliance on commercial enterprise offerings.

It provides utilities for preparing, transforming, and serving `.nupkg` packages for internal use and private feeds.

## Tools

* **[chomp](./chomp/)** — processes and rewrites Chocolatey packages for offline and internal deployment scenarios.
* **[muffin](./muffin/)** — a self-hosted NuGet v2-compatible feed server for serving `.nupkg` packages from a local repository.
