# Third-party notices

The demo site serves these unmodified third-party components alongside the
author's code. Each keeps its own license; the author's LICENSE does not apply
to them.

| Component | Version | License | Source |
|---|---|---|---|
| KaTeX (math rendering) | 0.16.22 | MIT | https://github.com/KaTeX/KaTeX (license file shipped at `assets/katex/LICENSE`) |
| Pyodide (Python in the browser) | 0.27.7 | Mozilla Public License 2.0 | https://github.com/pyodide/pyodide (source for this exact version: tag `0.27.7`) |
| CPython standard library (inside Pyodide) | 3.12.7 | Python Software Foundation License | https://github.com/python/cpython |
| PyYAML (Pyodide build) | 6.0.2 | MIT | https://github.com/yaml/pyyaml (license inside the wheel: `pyyaml-6.0.2.dist-info/licenses/LICENSE`) |

Python packages used at build or test time (PyYAML, pytest, Hypothesis, and,
optionally, the OpenAI and Anthropic SDKs) are installed by the package
manager under their own licenses and are not redistributed in this repository.
