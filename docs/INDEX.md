# Azazel Documentation

Azazel is a deterministic CUE-to-Zig build-model layer. Start with the production build path, then use the deeper references as needed.

## Start here

- [Getting Started](Getting-Started.md): prerequisites, validation, generation, build, and test commands.
- [Production Support Policy](PRODUCTION.md): supported Zig lanes, compatibility contract, experimental boundaries, and release gate.
- [Complete Build Reference](WIKI.md): schema fields, pipeline behavior, linking modes, package integration, generated imports, and troubleshooting.

## Architecture and validation

- [Architecture](Architecture.md): build-model and execution architecture.
- [Huge Zig Project Corpus](HUGE_PROJECT_CORPUS.md): real-project pressure testing and executable parity evidence.

## Repository policies

- [Contributing](../CONTRIBUTING.md): required end-to-end changes and verification commands.
- [Security](../SECURITY.md): security reporting and supported-surface guidance.
- [Experimental shared cache](../CACHE.md): current limitations and promotion criteria.

## Dogfood and experimental projects

Danzig is a VST3 framework retained in this repository as an integration workload. It is not part of the Azazel build-system API or production support contract. Its existing documentation remains available in [Danzig Complete Guide](Danzig-Complete-Guide.md), [VST3 Architecture](VST3-Architecture.md), and [Real-World Guide](Real-World-Guide.md) until the extraction tracked in issue #47 is complete.
